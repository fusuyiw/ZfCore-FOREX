//+------------------------------------------------------------------+
//| ZF Core Auto Executor EA                                         |
//| Executes signals exported by zf_core_scanner_v20.py              |
//| Signal file: MT5 Common Files / zf_ea_signals.csv                |
//+------------------------------------------------------------------+
#property strict
#property version   "2.00"

#include <Trade/Trade.mqh>

input bool   EnableAutoTrade        = true;
input string SignalFileName         = "zf_ea_signals.csv";
input long   MagicNumber            = 26061620;

input bool   UseScannerLot          = true;
input double FixedLot               = 0.01;
input double MaxLot                 = 1.00;
input int    MaxOpenExposures       = 5;
input int    MaxSpreadPoints        = 0;          // 0 = trust scanner's asset-aware spread gate
input bool   RequireStopLoss        = true;

input bool   EnableBuyLimit         = true;
input bool   EnableSellLimit        = true;
input int    LimitOffsetPoints      = 100;
input int    PendingExpiryMinutes   = 90;         // aligned with 6 x M15 calibration bars
input int    TimerSeconds           = 10;
input int    PulseCooldownMinutes   = 45;
input int    MaxDailyPulseEntries   = 8;

input bool   EnableTrailingStop     = true;
input double TrailingStartR         = 0.75;
input double TrailingDistanceR      = 0.55;

input bool   EnableFlipEngine       = true;
input double FlipMinConfidence      = 75.0;
input double FlipMinQuality         = 60.0;

input bool   EnableRecoveryLot      = true;
input double RecoveryBaseLot        = 0.01;
input int    RecoveryMaxSteps       = 3;

input double DefensiveDrawdownPct   = 5.0;
input double DefensiveLotFactor     = 0.50;
input double HardDrawdownPct        = 7.0;
input int    CooldownHours          = 24;

input bool   EnableDynamicTP        = true;
input double DynamicTPMinConfidence = 75.0;
input double DynamicTPMinQuality    = 60.0;
input double DynamicTPExtensionR    = 0.25;
input double DynamicTPMaxR          = 3.0;

CTrade trade;
string processedSignals[];
double peakEquity = 0.0;
string runtimeStatus = "INITIALIZING";

struct ZFSignal
{
   string signalId;
   datetime scanTime;
   int expireMinutes;
   string symbol;
   string direction;
   string action;
   string orderType;
   double lot;
   double entry;
   double sl;
   double tp;
   string timeframe;
   string exitMode;
   double confidence;
   double quality;
};

int OnInit()
{
   trade.SetExpertMagicNumber(MagicNumber);
   trade.SetDeviationInPoints(30);
   peakEquity = LoadPeakEquity();
   EventSetTimer(MathMax(TimerSeconds, 1));
   runtimeStatus = "ACTIVE";
   UpdateChartStatus();
   Print("ZF EA V2 aktif. Signal: Common/Files/", SignalFileName);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   Comment("");
}

void OnTick()
{
   UpdatePeakEquity();
   if(EnableTrailingStop)
      ManageTrailingStops();
   UpdateChartStatus();
}

void OnTimer()
{
   UpdatePeakEquity();
   if(!EnableAutoTrade)
   {
      runtimeStatus = "AUTO TRADE DISABLED";
      UpdateChartStatus();
      return;
   }

   if(!AccountRiskGuard())
   {
      UpdateChartStatus();
      return;
   }

   runtimeStatus = "READING SIGNALS";
   ReadAndExecuteSignals();
   runtimeStatus = "ACTIVE";
   UpdateChartStatus();
}

void OnTradeTransaction(
   const MqlTradeTransaction &trans,
   const MqlTradeRequest &request,
   const MqlTradeResult &result
)
{
   if(trans.type != TRADE_TRANSACTION_DEAL_ADD || trans.deal == 0)
      return;
   if(!HistoryDealSelect(trans.deal))
      return;
   if(HistoryDealGetInteger(trans.deal, DEAL_MAGIC) != MagicNumber)
      return;

   long entryType = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
   if(entryType != DEAL_ENTRY_OUT && entryType != DEAL_ENTRY_OUT_BY && entryType != DEAL_ENTRY_INOUT)
      return;

   string symbol = HistoryDealGetString(trans.deal, DEAL_SYMBOL);
   double netProfit =
      HistoryDealGetDouble(trans.deal, DEAL_PROFIT)
      + HistoryDealGetDouble(trans.deal, DEAL_SWAP)
      + HistoryDealGetDouble(trans.deal, DEAL_COMMISSION);

   if(netProfit < 0.0)
   {
      int nextStep = MathMin(GetRecoveryStep(symbol) + 1, MathMax(RecoveryMaxSteps, 0));
      SetRecoveryStep(symbol, nextStep);
      Print("ZF RECOVERY: ", symbol, " step=", nextStep, " net=", netProfit);
   }
   else if(netProfit > 0.0)
   {
      SetRecoveryStep(symbol, 0);
      Print("ZF RECOVERY RESET: ", symbol, " net=", netProfit);
   }
}

string StateKey(string suffix, string symbol = "")
{
   string key = "ZF2_" + suffix + "_" + IntegerToString((int)MagicNumber);
   return symbol == "" ? key : key + "_" + symbol;
}

double LoadPeakEquity()
{
   string key = StateKey("PEAK");
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(!GlobalVariableCheck(key))
      GlobalVariableSet(key, equity);
   return MathMax(GlobalVariableGet(key), equity);
}

void UpdatePeakEquity()
{
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   if(equity > peakEquity)
   {
      peakEquity = equity;
      GlobalVariableSet(StateKey("PEAK"), peakEquity);
   }
}

double CurrentDrawdownPct()
{
   if(peakEquity <= 0.0)
      peakEquity = LoadPeakEquity();
   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   return peakEquity > 0.0 ? MathMax((peakEquity - equity) / peakEquity * 100.0, 0.0) : 0.0;
}

datetime CooldownUntil()
{
   string key = StateKey("COOLDOWN");
   return GlobalVariableCheck(key) ? (datetime)GlobalVariableGet(key) : 0;
}

void SetCooldownUntil(datetime value)
{
   GlobalVariableSet(StateKey("COOLDOWN"), (double)value);
}

int GetRecoveryStep(string symbol)
{
   string key = StateKey("RECOVERY", symbol);
   if(!GlobalVariableCheck(key))
      return 0;
   return (int)MathMax(0, MathMin((int)GlobalVariableGet(key), RecoveryMaxSteps));
}

void SetRecoveryStep(string symbol, int step)
{
   GlobalVariableSet(StateKey("RECOVERY", symbol), MathMax(0, MathMin(step, RecoveryMaxSteps)));
}

void SaveInitialRisk(string symbol, double risk)
{
   if(risk > 0.0)
      GlobalVariableSet(StateKey("RISK", symbol), risk);
}

double LoadInitialRisk(string symbol, double fallback)
{
   string key = StateKey("RISK", symbol);
   if(GlobalVariableCheck(key) && GlobalVariableGet(key) > 0.0)
      return GlobalVariableGet(key);
   if(fallback > 0.0)
      SaveInitialRisk(symbol, fallback);
   return fallback;
}

bool AccountRiskGuard()
{
   datetime cooldown = CooldownUntil();
   if(cooldown > TimeCurrent())
   {
      runtimeStatus = "COOLDOWN UNTIL " + TimeToString(cooldown, TIME_DATE | TIME_MINUTES);
      return false;
   }

   double drawdown = CurrentDrawdownPct();
   if(drawdown < HardDrawdownPct)
      return true;

   CloseAllMagicExposure();
   SetCooldownUntil(TimeCurrent() + MathMax(CooldownHours, 1) * 3600);
   runtimeStatus = "HARD DRAWDOWN COOLDOWN";
   Print("ZF HARD GUARD: drawdown=", drawdown, "%");
   return false;
}

void CloseAllMagicExposure()
{
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket > 0 && OrderGetInteger(ORDER_MAGIC) == MagicNumber)
         trade.OrderDelete(ticket);
   }

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket > 0 && PositionGetInteger(POSITION_MAGIC) == MagicNumber)
         trade.PositionClose(ticket);
   }
}

int CountMagicPositions(string symbol = "")
{
   int count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || PositionGetInteger(POSITION_MAGIC) != MagicNumber)
         continue;
      if(symbol == "" || PositionGetString(POSITION_SYMBOL) == symbol)
         count++;
   }
   return count;
}

int CountMagicOrders(string symbol = "")
{
   int count = 0;
   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0 || OrderGetInteger(ORDER_MAGIC) != MagicNumber)
         continue;
      if(symbol == "" || OrderGetString(ORDER_SYMBOL) == symbol)
         count++;
   }
   return count;
}

int CountMagicExposure()
{
   return CountMagicPositions() + CountMagicOrders();
}

bool AlreadyProcessed(string signalId)
{
   for(int i = 0; i < ArraySize(processedSignals); i++)
      if(processedSignals[i] == signalId)
         return true;
   return false;
}

void MarkProcessed(string signalId)
{
   if(signalId == "" || AlreadyProcessed(signalId))
      return;
   int size = ArraySize(processedSignals);
   ArrayResize(processedSignals, size + 1);
   processedSignals[size] = signalId;
}

uint SignalHash(string text)
{
   uint hash = 2166136261;
   for(int i = 0; i < StringLen(text); i++)
   {
      hash ^= (uint)StringGetCharacter(text, i);
      hash *= 16777619;
   }
   return hash;
}

string SignalClaimKey(string signalId)
{
   return "ZF_CLAIM_" + IntegerToString((int)MagicNumber) + "_" + IntegerToString((int)SignalHash(signalId));
}

bool ClaimSignalGlobally(string signalId)
{
   string key = SignalClaimKey(signalId);
   if(!GlobalVariableCheck(key))
      GlobalVariableSet(key, 0.0);

   double previous = GlobalVariableGet(key);
   double nowValue = (double)TimeCurrent();
   if(previous > 0.0 && previous >= nowValue - 86400.0)
      return false;

   return GlobalVariableSetOnCondition(key, nowValue, previous);
}

void ReleaseSignalClaim(string signalId)
{
   string key = SignalClaimKey(signalId);
   if(GlobalVariableCheck(key))
      GlobalVariableSet(key, 0.0);
}

bool IsPulseSignal(ZFSignal &sig)
{
   return sig.action == "EKSEKUSI_PULSE";
}

string PulseLastKey(string symbol)
{
   return StateKey("PULSE_LAST", symbol);
}

string PulseDailyKey()
{
   MqlDateTime nowParts;
   TimeToStruct(TimeCurrent(), nowParts);
   return StateKey(
      "PULSE_DAY_" + IntegerToString(nowParts.year) + IntegerToString(nowParts.mon) + IntegerToString(nowParts.day)
   );
}

bool PulseCadenceAllowed(string symbol)
{
   string lastKey = PulseLastKey(symbol);
   if(GlobalVariableCheck(lastKey))
   {
      datetime lastEntry = (datetime)GlobalVariableGet(lastKey);
      if(TimeCurrent() < lastEntry + MathMax(PulseCooldownMinutes, 1) * 60)
         return false;
   }
   string dayKey = PulseDailyKey();
   double dailyCount = GlobalVariableCheck(dayKey) ? GlobalVariableGet(dayKey) : 0.0;
   return dailyCount < MathMax(MaxDailyPulseEntries, 1);
}

void RecordPulseEntry(string symbol)
{
   GlobalVariableSet(PulseLastKey(symbol), (double)TimeCurrent());
   string dayKey = PulseDailyKey();
   double dailyCount = GlobalVariableCheck(dayKey) ? GlobalVariableGet(dayKey) : 0.0;
   GlobalVariableSet(dayKey, dailyCount + 1.0);
}

bool ReadSignalRow(int handle, ZFSignal &sig)
{
   string signalId = FileReadString(handle);
   if(signalId == "" && FileIsEnding(handle))
      return false;

   string scanTimeText = FileReadString(handle);
   string scanEpochText = FileReadString(handle);
   string expireText = FileReadString(handle);
   sig.symbol = FileReadString(handle);
   sig.direction = FileReadString(handle);
   sig.action = FileReadString(handle);
   sig.orderType = FileReadString(handle);
   sig.lot = StringToDouble(FileReadString(handle));
   sig.entry = StringToDouble(FileReadString(handle));
   sig.sl = StringToDouble(FileReadString(handle));
   sig.tp = StringToDouble(FileReadString(handle));
   FileReadString(handle); // TP pips
   sig.timeframe = FileReadString(handle);
   sig.exitMode = FileReadString(handle);
   sig.confidence = StringToDouble(FileReadString(handle));
   sig.quality = StringToDouble(FileReadString(handle));
   FileReadString(handle); // note

   sig.signalId = signalId;
   long epoch = StringToInteger(scanEpochText);
   sig.scanTime = epoch > 0 ? (datetime)epoch : StringToTime(scanTimeText);
   sig.expireMinutes = (int)StringToInteger(expireText);
   return true;
}

void ReadAndExecuteSignals()
{
   int handle = INVALID_HANDLE;
   for(int attempt = 0; attempt < 3 && handle == INVALID_HANDLE; attempt++)
   {
      ResetLastError();
      handle = FileOpen(
         SignalFileName,
         FILE_READ | FILE_CSV | FILE_COMMON | FILE_ANSI | FILE_SHARE_READ | FILE_SHARE_WRITE,
         ';'
      );
      if(handle == INVALID_HANDLE)
         Sleep(150);
   }
   if(handle == INVALID_HANDLE)
   {
      runtimeStatus = "SIGNAL FILE NOT FOUND";
      Print("ZF FILE ERROR: ", SignalFileName, " code=", GetLastError());
      return;
   }

   bool header = true;
   while(!FileIsEnding(handle))
   {
      ZFSignal sig;
      if(!ReadSignalRow(handle, sig))
         break;
      if(header)
      {
         header = false;
         continue;
      }
      ExecuteSignal(sig);
   }
   FileClose(handle);
}

void ExecuteSignal(ZFSignal &sig)
{
   if(sig.signalId == "" || AlreadyProcessed(sig.signalId))
      return;
   if(
      (sig.action != "EKSEKUSI" && sig.action != "EKSEKUSI_TERBATAS" && sig.action != "EKSEKUSI_PULSE")
      || (sig.direction != "BUY" && sig.direction != "SELL")
   )
      return;

   if(sig.expireMinutes <= 0 || TimeCurrent() > sig.scanTime + sig.expireMinutes * 60)
   {
      Print("ZF SKIP EXPIRED: ", sig.signalId);
      MarkProcessed(sig.signalId);
      return;
   }
   if(sig.tp <= 0.0 || (RequireStopLoss && sig.sl <= 0.0))
   {
      Print("ZF SKIP INVALID SL/TP: ", sig.signalId);
      MarkProcessed(sig.signalId);
      return;
   }
   if(!SymbolSelect(sig.symbol, true))
   {
      Print("ZF SKIP SYMBOL: ", sig.symbol);
      MarkProcessed(sig.signalId);
      return;
   }
   if(IsPulseSignal(sig) && !PulseCadenceAllowed(sig.symbol))
   {
      Print("ZF PULSE CADENCE BLOCKED: ", sig.symbol);
      MarkProcessed(sig.signalId);
      return;
   }

   int preparation = PrepareSymbol(sig);
   if(preparation <= 0)
      return;

   if(CountMagicExposure() >= MaxOpenExposures)
   {
      Print("ZF GUARD MAX EXPOSURE: ", CountMagicExposure(), "/", MaxOpenExposures);
      return;
   }

   long spread = SymbolInfoInteger(sig.symbol, SYMBOL_SPREAD);
   if(MaxSpreadPoints > 0 && spread > MaxSpreadPoints)
   {
      Print("ZF SKIP SPREAD: ", sig.symbol, " spread=", spread);
      return;
   }

   double requestedLot = UseScannerLot ? sig.lot : FixedLot;
   if(EnableRecoveryLot && sig.action != "EKSEKUSI_TERBATAS" && !IsPulseSignal(sig))
      requestedLot += GetRecoveryStep(sig.symbol) * MathMax(RecoveryBaseLot, 0.0);
   if(CurrentDrawdownPct() >= DefensiveDrawdownPct)
      requestedLot *= MathMax(MathMin(DefensiveLotFactor, 1.0), 0.01);

   double lot = NormalizeLot(sig.symbol, MathMin(requestedLot, MaxLot));
   if(lot <= 0.0)
   {
      Print("ZF SKIP LOT: ", sig.symbol);
      MarkProcessed(sig.signalId);
      return;
   }

   int digits = (int)SymbolInfoInteger(sig.symbol, SYMBOL_DIGITS);
   double sl = sig.sl > 0.0 ? NormalizeDouble(sig.sl, digits) : 0.0;
   double tp = NormalizeDouble(sig.tp, digits);
   if(!ClaimSignalGlobally(sig.signalId))
   {
      Print("ZF DUPLICATE CLAIM BLOCKED: ", sig.signalId);
      MarkProcessed(sig.signalId);
      return;
   }
   bool success = PlaceSignalOrder(sig, lot, sl, tp);

   if(success)
   {
      if(IsPulseSignal(sig))
         RecordPulseEntry(sig.symbol);
      MarkProcessed(sig.signalId);
      runtimeStatus = "LAST EXECUTED " + sig.symbol + " " + sig.orderType;
   }
   else
   {
      ReleaseSignalClaim(sig.signalId);
   }
}

bool PlaceSignalOrder(ZFSignal &sig, double lot, double sl, double tp)
{
   string orderType = sig.orderType == "" ? sig.direction : sig.orderType;
   int digits = (int)SymbolInfoInteger(sig.symbol, SYMBOL_DIGITS);
   double point = SymbolInfoDouble(sig.symbol, SYMBOL_POINT);
   int stopLevel = (int)SymbolInfoInteger(sig.symbol, SYMBOL_TRADE_STOPS_LEVEL);
   int distancePoints = (int)MathMax(LimitOffsetPoints, stopLevel + 1);
   double entryPrice = sig.entry;
   bool ok = false;

   if(sig.direction == "BUY" && orderType == "BUY_LIMIT" && EnableBuyLimit)
   {
      double ask = SymbolInfoDouble(sig.symbol, SYMBOL_ASK);
      double maximumPrice = ask - distancePoints * point;
      entryPrice = sig.entry > 0.0 ? MathMin(sig.entry, maximumPrice) : maximumPrice;
      entryPrice = NormalizeDouble(entryPrice, digits);
      if(sl >= entryPrice || tp <= entryPrice)
         return LogInvalidLevels(sig, entryPrice, sl, tp);
      datetime expiry = TimeCurrent() + MathMax(PendingExpiryMinutes, 1) * 60;
      ok = trade.BuyLimit(lot, entryPrice, sig.symbol, sl, tp, ORDER_TIME_SPECIFIED, expiry, OrderComment(sig));
   }
   else if(sig.direction == "SELL" && orderType == "SELL_LIMIT" && EnableSellLimit)
   {
      double bid = SymbolInfoDouble(sig.symbol, SYMBOL_BID);
      double minimumPrice = bid + distancePoints * point;
      entryPrice = sig.entry > 0.0 ? MathMax(sig.entry, minimumPrice) : minimumPrice;
      entryPrice = NormalizeDouble(entryPrice, digits);
      if(sl <= entryPrice || tp >= entryPrice)
         return LogInvalidLevels(sig, entryPrice, sl, tp);
      datetime expiry = TimeCurrent() + MathMax(PendingExpiryMinutes, 1) * 60;
      ok = trade.SellLimit(lot, entryPrice, sig.symbol, sl, tp, ORDER_TIME_SPECIFIED, expiry, OrderComment(sig));
   }
   else if(sig.direction == "BUY")
   {
      entryPrice = SymbolInfoDouble(sig.symbol, SYMBOL_ASK);
      ok = trade.Buy(lot, sig.symbol, 0.0, sl, tp, OrderComment(sig));
   }
   else
   {
      entryPrice = SymbolInfoDouble(sig.symbol, SYMBOL_BID);
      ok = trade.Sell(lot, sig.symbol, 0.0, sl, tp, OrderComment(sig));
   }

   if(ok)
   {
      SaveInitialRisk(sig.symbol, MathAbs(entryPrice - sl));
      Print(
         "ZF EXECUTED: ", sig.symbol, " ", orderType,
         " lot=", lot, " entry=", entryPrice, " sl=", sl, " tp=", tp,
         " signal=", sig.signalId
      );
      return true;
   }

   Print(
      "ZF TRADE ERROR: ", sig.symbol,
      " retcode=", trade.ResultRetcode(),
      " ", trade.ResultRetcodeDescription()
   );
   return false;
}

bool LogInvalidLevels(ZFSignal &sig, double entry, double sl, double tp)
{
   Print("ZF INVALID LEVELS: ", sig.symbol, " entry=", entry, " sl=", sl, " tp=", tp);
   MarkProcessed(sig.signalId);
   return false;
}

string OrderComment(ZFSignal &sig)
{
   return "ZF2 " + sig.timeframe + " " + sig.exitMode;
}

int PrepareSymbol(ZFSignal &sig)
{
   bool samePosition = false;
   bool oppositePosition = false;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || PositionGetInteger(POSITION_MAGIC) != MagicNumber)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != sig.symbol)
         continue;

      long type = PositionGetInteger(POSITION_TYPE);
      bool same =
         (type == POSITION_TYPE_BUY && sig.direction == "BUY")
         || (type == POSITION_TYPE_SELL && sig.direction == "SELL");
      samePosition = samePosition || same;
      oppositePosition = oppositePosition || !same;
   }

   if(samePosition)
   {
      TryExtendTakeProfit(sig);
      Print("ZF HOLD SAME POSITION: ", sig.symbol);
      MarkProcessed(sig.signalId);
      return 0;
   }

   if(oppositePosition)
   {
      if(!EnableFlipEngine || sig.confidence < FlipMinConfidence || sig.quality < FlipMinQuality)
      {
         Print("ZF FLIP BLOCKED: ", sig.symbol);
         MarkProcessed(sig.signalId);
         return 0;
      }

      for(int i = PositionsTotal() - 1; i >= 0; i--)
      {
         ulong ticket = PositionGetTicket(i);
         if(ticket == 0 || PositionGetInteger(POSITION_MAGIC) != MagicNumber)
            continue;
         if(PositionGetString(POSITION_SYMBOL) != sig.symbol)
            continue;
         if(!trade.PositionClose(ticket))
         {
            Print("ZF FLIP CLOSE ERROR: ", sig.symbol, " ", trade.ResultRetcodeDescription());
            return -1;
         }
      }
      Print("ZF FLIP CONFIRMED: ", sig.symbol, " -> ", sig.direction);
   }

   for(int i = OrdersTotal() - 1; i >= 0; i--)
   {
      ulong ticket = OrderGetTicket(i);
      if(ticket == 0 || OrderGetInteger(ORDER_MAGIC) != MagicNumber)
         continue;
      if(OrderGetString(ORDER_SYMBOL) != sig.symbol)
         continue;

      string typeText = EnumToString((ENUM_ORDER_TYPE)OrderGetInteger(ORDER_TYPE));
      bool orderBuy = StringFind(typeText, "BUY") >= 0;
      bool sameOrder = (orderBuy && sig.direction == "BUY") || (!orderBuy && sig.direction == "SELL");
      if(sameOrder && !oppositePosition)
      {
         Print("ZF HOLD SAME ORDER: ", sig.symbol);
         MarkProcessed(sig.signalId);
         return 0;
      }
      if(!trade.OrderDelete(ticket))
      {
         Print("ZF ORDER DELETE ERROR: ", sig.symbol, " ", trade.ResultRetcodeDescription());
         return -1;
      }
   }

   return 1;
}

bool TryExtendTakeProfit(ZFSignal &sig)
{
   if(!EnableDynamicTP || sig.confidence < DynamicTPMinConfidence || sig.quality < DynamicTPMinQuality)
      return false;

   bool changed = false;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || PositionGetInteger(POSITION_MAGIC) != MagicNumber)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != sig.symbol)
         continue;

      long type = PositionGetInteger(POSITION_TYPE);
      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double currentSl = PositionGetDouble(POSITION_SL);
      double currentTp = PositionGetDouble(POSITION_TP);
      double initialRisk = LoadInitialRisk(sig.symbol, MathAbs(openPrice - currentSl));
      if(initialRisk <= 0.0 || currentTp <= 0.0)
         continue;

      int digits = (int)SymbolInfoInteger(sig.symbol, SYMBOL_DIGITS);
      double proposedTp;
      if(type == POSITION_TYPE_BUY)
      {
         double cap = openPrice + initialRisk * DynamicTPMaxR;
         proposedTp = NormalizeDouble(MathMin(currentTp + initialRisk * DynamicTPExtensionR, cap), digits);
         if(proposedTp > currentTp)
            changed = trade.PositionModify(ticket, currentSl, proposedTp) || changed;
      }
      else
      {
         double cap = openPrice - initialRisk * DynamicTPMaxR;
         proposedTp = NormalizeDouble(MathMax(currentTp - initialRisk * DynamicTPExtensionR, cap), digits);
         if(proposedTp < currentTp)
            changed = trade.PositionModify(ticket, currentSl, proposedTp) || changed;
      }
   }
   return changed;
}

double NormalizeLot(string symbol, double lot)
{
   double minLot = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MIN);
   double brokerMax = SymbolInfoDouble(symbol, SYMBOL_VOLUME_MAX);
   double step = SymbolInfoDouble(symbol, SYMBOL_VOLUME_STEP);
   if(step <= 0.0)
      step = 0.01;

   lot = MathMax(lot, minLot);
   lot = MathMin(lot, MathMin(brokerMax, MaxLot));
   lot = MathFloor((lot + 1e-9) / step) * step;
   return NormalizeDouble(lot, 2);
}

void ManageTrailingStops()
{
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0 || PositionGetInteger(POSITION_MAGIC) != MagicNumber)
         continue;

      string symbol = PositionGetString(POSITION_SYMBOL);
      long type = PositionGetInteger(POSITION_TYPE);
      double openPrice = PositionGetDouble(POSITION_PRICE_OPEN);
      double currentSl = PositionGetDouble(POSITION_SL);
      double currentTp = PositionGetDouble(POSITION_TP);
      if(currentSl <= 0.0)
         continue;

      double point = SymbolInfoDouble(symbol, SYMBOL_POINT);
      int digits = (int)SymbolInfoInteger(symbol, SYMBOL_DIGITS);
      int stopLevel = (int)SymbolInfoInteger(symbol, SYMBOL_TRADE_STOPS_LEVEL);
      double minimumDistance = (stopLevel + 1) * point;
      double initialRisk = LoadInitialRisk(symbol, MathAbs(openPrice - currentSl));
      if(initialRisk <= 0.0)
         continue;

      if(type == POSITION_TYPE_BUY)
      {
         double bid = SymbolInfoDouble(symbol, SYMBOL_BID);
         if(bid - openPrice < initialRisk * TrailingStartR)
            continue;
         double proposedSl = MathMin(bid - initialRisk * TrailingDistanceR, bid - minimumDistance);
         proposedSl = NormalizeDouble(proposedSl, digits);
         if(proposedSl > currentSl && proposedSl < bid)
            trade.PositionModify(ticket, proposedSl, currentTp);
      }
      else
      {
         double ask = SymbolInfoDouble(symbol, SYMBOL_ASK);
         if(openPrice - ask < initialRisk * TrailingStartR)
            continue;
         double proposedSl = MathMax(ask + initialRisk * TrailingDistanceR, ask + minimumDistance);
         proposedSl = NormalizeDouble(proposedSl, digits);
         if(proposedSl < currentSl && proposedSl > ask)
            trade.PositionModify(ticket, proposedSl, currentTp);
      }
   }
}

void UpdateChartStatus()
{
   Comment(
      "ZF Core Auto Executor V2\n",
      "Status: ", runtimeStatus, "\n",
      "AutoTrade: ", (EnableAutoTrade ? "ON" : "OFF"),
      " | Terminal: ", (TerminalInfoInteger(TERMINAL_TRADE_ALLOWED) ? "ON" : "OFF"), "\n",
      "Signal: Common/Files/", SignalFileName, "\n",
      "Exposure: ", CountMagicExposure(), "/", MaxOpenExposures,
      " | Max lot: ", DoubleToString(MaxLot, 2), "\n",
      "Flip: ", (EnableFlipEngine ? "ON" : "OFF"),
      " | Recovery: ", (EnableRecoveryLot ? "ON" : "OFF"),
      " | Trailing: ", (EnableTrailingStop ? "ON" : "OFF"), "\n",
      "Drawdown: ", DoubleToString(CurrentDrawdownPct(), 2), "%\n",
      "Heartbeat: ", TimeToString(TimeCurrent(), TIME_DATE | TIME_SECONDS)
   );
}
