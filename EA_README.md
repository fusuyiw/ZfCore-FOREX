# ZF Core Auto Executor EA

EA ini adalah eksekutor otomatis untuk sinyal dari `zf_core_scanner_v20.py`.

## Alur Kerja

1. Jalankan MT5 Exness demo.
2. Jalankan `zf_core_scanner_v20.py`.
3. Scanner menulis sinyal ke Common Files MT5:
   `zf_ea_signals.csv`
4. EA membaca file itu dan membuka posisi otomatis untuk sinyal `EKSEKUSI`.
5. Live learning tetap berjalan di V20 karena sinyal TOP tetap dicatat oleh scanner.

## Cara Pasang EA

1. Buka MT5.
2. Klik `File > Open Data Folder`.
3. Masuk ke `MQL5/Experts`.
4. Salin file `ZF_Core_AutoExecutor_EA.mq5` ke folder tersebut.
5. Buka MetaEditor, compile EA.
6. Pasang EA ke chart apa saja.
7. Aktifkan `Algo Trading`.

## Setting Penting

- `EnableAutoTrade=true`
- `SignalFileName=zf_ea_signals.csv`
- `MagicNumber=26061620`
- `UseScannerLot=true`
- `MaxLot=1.0`
- `FixedLot=0.01`
- `MaxOpenPositions=3`
- `EquityStopPercent=20`
- `RequireStopLoss=true`
- `EnableBuyLimitOrders=true`
- `BuyLimitOffsetPoints=100`
- `EnableSellLimitOrders=true`
- `SellLimitOffsetPoints=100`
- `PendingExpiryMinutes=15`
- `EnableTrailingStop=true`
- `TrailingStartR=0.75`
- `TrailingDistanceR=0.55`
- `EnableFlipEngine=true`
- `FlipMinConfidence=75`
- `FlipMinQuality=60`
- `EnableRecoveryLot=true`
- `RecoveryBaseLot=0.01`
- `RecoveryMaxSteps=3`
- `DefensiveDrawdownPct=5`
- `HardDrawdownPct=7`
- `CooldownHours=24`
- `EnableDynamicTP=true`

Jika scanner mengirim `OrderType=BUY_LIMIT`, EA akan memasang pending order `BuyLimit`.
Harga limit harus berada di bawah Ask; bila harga entry dari scanner terlalu dekat/di atas Ask, EA menyesuaikan jaraknya memakai `BuyLimitOffsetPoints` dan minimum stop-level broker.
Jika scanner mengirim `OrderType=SELL_LIMIT`, EA akan memasang pending order `SellLimit`.
Harga limit harus berada di atas Bid; bila harga entry dari scanner terlalu dekat/di bawah Bid, EA menyesuaikan jaraknya memakai `SellLimitOffsetPoints` dan minimum stop-level broker.
Trailing stop aktif setelah posisi bergerak sekitar `TrailingStartR` kali risiko awal. Jarak trailing mengikuti `TrailingDistanceR` kali risiko awal.

Flip hanya dilakukan saat ada sinyal berlawanan yang memenuhi batas confidence dan quality. Recovery lot bertambah secara aritmetika, dibatasi `RecoveryMaxSteps`, dan tetap tidak boleh melewati `MaxLot`.

Saat drawdown mencapai 5%, lot baru diperkecil. Saat drawdown mencapai 7%, EA menutup exposure dengan magic number yang sama dan masuk cooling-down 24 jam. Dynamic TP hanya memperluas target ketika sinyal baru masih searah dan lolos batas kualitas.

Dengan `UseScannerLot=true`, EA memakai lot hasil hitungan scanner, lalu tetap dibatasi oleh `MaxLot`. Jika ingin memaksa lot tetap kecil, ubah `UseScannerLot=false` dan atur `FixedLot`.

Untuk akun demo, default ini mengikuti rumus scanner. Untuk akun real, jangan gunakan tanpa pengujian forward yang panjang.

## Catatan Risiko

EA ini diwajibkan memakai TP dan SL. Jika scanner mengirim sinyal tanpa SL, EA akan menolaknya. Recovery dan flip tidak menjamin rangkaian transaksi akan profit; gunakan demo sampai hasil forward test stabil.
