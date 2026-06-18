# ZF Core Scanner Forex

ZF Core Scanner adalah aplikasi scanner pasar Forex berbasis konsep **Zuhri Formalism (ZF-Core)**. Aplikasi ini dibuat untuk membaca struktur pasar, mengukur tekanan resonansi harga, memetakan anomali, dan memberi rekomendasi scanner berupa arah, lot, entry, stop loss, take profit, points, quality score, dan catatan risiko.

> Aplikasi ini adalah **alat bantu scanner dan pembelajaran**, bukan robot eksekusi otomatis, bukan nasihat keuangan, dan bukan jaminan profit.

## Sumber Konsep

Dasar konseptual aplikasi ini berasal dari **Buku Besar Forex ZF** atau **Buku ZF-Core** yang diberikan oleh Arsitek pada awal proses pengembangan. Buku tersebut berisi 9 bab utama tentang:

1. Ontologi pasar dan struktur resonansi.
2. Mekanika data, sinkronisasi, dan integritas data.
3. Analisis order book dan pemetaan likuiditas.
4. Formulasi matematis resonansi ZF-Core.
5. Protokol eksekusi dan manajemen posisi.
6. Mitigasi anomali dan mode dingin.
7. Akuisisi data multi-asset.
8. Validasi silang, anomaly engine, dan memori sesi.
9. Penyimpanan otonom dan arsip dinamis.

ZF Core Scanner adalah implementasi praktis dari prinsip-prinsip tersebut dalam bentuk scanner berbasis Python.

## Kredit Dan Takzim

Dengan penuh takzim, kredit spiritual dan konseptual aplikasi ini dibebankan kepada:

**Guru kami, Syaikh Muhammad Zuhri, yang kami takzimi.**

Semoga karya kecil ini menjadi wasilah manfaat, adab, disiplin, dan kehati-hatian dalam membaca pasar. ZF Core Scanner tidak dimaksudkan untuk melahirkan sikap serakah, tergesa-gesa, atau berjudi di pasar, melainkan untuk membantu pengguna membaca data dengan lebih tertib dan sadar risiko.

## Syarat Penggunaan

Pengguna yang ingin memakai scanner ini disyaratkan:

**baksos FK**.

1. Sudah mengikuti program **baksos FK**. (jika belum silahkan kunjungi FB:fatwa kehidupan)
2. Memahami bahwa scanner ini hanya alat bantu analisis.
3. Tidak menggunakan aplikasi ini untuk tindakan spekulatif yang sembrono.
4. **Menggunakan akun demo** atau simulasi terlebih dahulu sebelum mempertimbangkan akun real.
5. Bertanggung jawab penuh atas setiap keputusan trading yang dilakukan.

Jika belum mengikuti program baksos FK, pengguna tidak disarankan memakai scanner ini.

## Fitur Utama

- Scan multi-pair berbasis timeframe M15/M30/H4/W1.
- Perhitungan `P_pure`, `D_res`, `ZF_Score`, `Decay_Integral`, dan `Lambda_Liquidity`.
- Proyeksi arah sesuai timeframe aktif, termasuk 15 menit.
- Dynamic stop loss dan take profit.
- Output lot, entry price, SL price, TP price, SL points, dan TP points.
- Risk engine dengan mode normal, liquidity lock, slippage lock, circuit breaker, dan cold mode.
- Historical validation.
- Live learning dari hasil proyeksi vs hasil real.
- Archival vault untuk menyimpan memori sesi.
- Self-healing optimizer berbasis hasil live.
- Optimasi historis mingguan dengan jendela berjalan 60 hari.
- Fractional Kelly konservatif yang hanya mengurangi risiko dasar.
- Data publik OKX untuk funding rate dan open interest crypto.
- Flip engine terkonfirmasi, bounded recovery, drawdown cooldown, dan dynamic TP pada EA.
- Provider data:
  - `MT5` untuk penggunaan lokal dengan MetaTrader 5.
  - `YFINANCE` untuk mode Docker/NAS atau environment tanpa MT5.

## Struktur Folder

```text
FOREX/
  zf_core_scanner.py
  zf_historical_validator.py
  README.md
  .env
  zf_archival_vault/
  zf_live_learning/
  zf_profiles/
  zf_validation_reports/
  _unused_backup/
```

Folder data seperti `zf_archival_vault`, `zf_live_learning`, `zf_profiles`, dan `zf_validation_reports` adalah memori lokal aplikasi. Folder tersebut tidak wajib dipush ke GitHub.

## Instalasi Lokal Windows

Pastikan Python sudah terpasang. Contoh penggunaan:

```powershell
cd D:\FOREX
pip install MetaTrader5 pandas numpy yfinance requests
```

Jika memakai MT5:

1. Buka MetaTrader 5.
2. Login ke akun broker.
3. Pastikan symbol broker tersedia di Market Watch.
4. Jalankan scanner.

## Konfigurasi `.env`

Contoh `.env`:

```text
FINNHUB_API_KEY=isi_api_key_opsional
ALPHA_VANTAGE_API_KEY=isi_api_key_opsional
ZF_DATA_PROVIDER=MT5
MT5_SYMBOL_SUFFIXES=
```

`MT5_SYMBOL_SUFFIXES` boleh dikosongkan agar scanner membaca semua symbol MT5 yang relevan. Jika ingin membatasi broker tertentu, isi seperti `.m,.pro`.

Untuk mode yfinance:

```text
ZF_DATA_PROVIDER=YFINANCE
YFINANCE_ACCOUNT_EQUITY_FALLBACK=1000
YFINANCE_SYMBOLS=EURUSD.yf,GBPUSD.yf,AUDUSD.yf,USDJPY.yf,XAUUSD.yf
```

Catatan: `.env` berisi konfigurasi lokal dan tidak boleh dipush jika berisi token atau key pribadi.

## Cara Menjalankan Scanner

Jalankan sekali:

```powershell
python zf_core_scanner_v20.py --once
```

Jalankan sebagai service M30:

```powershell
python zf_core_scanner_v20.py --service
```

Untuk membaca proyeksi 15 menit, isi konfigurasi:

```text
ZF_DEFAULT_SCAN_TIMEFRAME=M15
ZF_USE_PROFILE_TIMEFRAMES=0
ZF_USE_FIBO_FILTER=1
ZF_MIN_EXECUTION_ZF_SCORE=0.50
ZF_EA_BUY_ORDER_TYPE=BUY_LIMIT
ZF_EA_SELL_ORDER_TYPE=SELL_LIMIT
ZF_EA_MAGIC_NUMBER=26061620
ZF_EA_MAX_LOT=1.0
ZF_SYNC_MT5_FORWARD_RESULTS=1
```

Dengan konfigurasi tersebut, sinyal BUY yang lolos `EKSEKUSI` akan diekspor ke EA sebagai `BUY_LIMIT`, dan sinyal SELL sebagai `SELL_LIMIT`.
Jika ingin scanner kembali memakai timeframe terbaik dari hasil backtest per pair, ubah `ZF_USE_PROFILE_TIMEFRAMES=1`.
Mode Fibo tetap tunduk pada prinsip ZF: Fibo hanya menjadi filter re-entry dan penentu harga limit, sementara arah utama tetap berasal dari `D_res`, `Decay_Integral`, dan `ZF_Score`.

Gold dapat dijadikan focus symbol:

```text
ZF_ASSET_CLASSES=forex,energy,metal,crypto
ZF_FOCUS_SYMBOLS=XAUUSDm
ZF_METAL_MIN_DRIFT=1.0
ZF_METAL_REQUIRE_TREND=1
```

Dengan mode ini, Gold tetap dipindai, tetapi OP hanya dibuka saat resonansi metal ekstrem: drift minimal 1.0 dan regime `TREND`.

Forward-test learning aktif jika EA demo memakai `MagicNumber` yang sama. Scanner akan membaca closed deal dari history MT5, menyimpannya ke `zf_live_learning/mt5_forward_deals.csv`, lalu memasukkannya ke live learning agar optimizer menyesuaikan parameter dari hasil demo nyata.

Konteks crypto OKX menggunakan endpoint publik resmi dan tidak membutuhkan API key:

```text
ZF_OKX_PUBLIC_DATA_ENABLED=1
ZF_OKX_BASE_URL=https://www.okx.com
ZF_OKX_REQUIRE_CRYPTO_DATA=0
```

Funding rate dan perubahan open interest menjadi sensor tambahan ZF, bukan pengganti data harga MT5. Jika OKX sedang tidak tersedia dan `ZF_OKX_REQUIRE_CRYPTO_DATA=0`, scanner mencatat kegagalan tersebut tetapi tetap dapat menganalisis aset lain.

Jika tidak memakai argumen, aplikasi mengikuti konfigurasi default di script.

## Cara Membaca Output

Contoh output sinyal:

```text
EURUSD.m | PROYEKSI 30M | Lot: 0.05 | Entry: 1.08500 | SL: 1.08350 (150 points) | TP: 1.08700 (200 points) | RR: 1.33
```

Makna kolom:

- `Lot`: rekomendasi ukuran lot berdasarkan risk engine.
- `Entry`: harga referensi saat scanner membaca data.
- `SL`: harga stop loss final.
- `TP`: harga take profit final.
- `points`: jarak broker dalam points, lebih praktis untuk market execution.
- `RR`: reward-to-risk ratio.
- `Quality`: skor kualitas sinyal.
- `Conf`: confidence scanner.
- `Saran`: rekomendasi bahasa Indonesia untuk pengguna awam.

## Historical Validation

Untuk validasi historis:

```powershell
python zf_historical_validator.py
```

Hasil validasi akan disimpan ke:

```text
zf_validation_reports/
```

Scanner akan memakai hasil ini untuk membedakan pair `TRADEABLE`, `WATCH_ONLY`, dan `AVOID`.

## Live Learning

Saat scanner berjalan, aplikasi menyimpan sinyal terbuka dan hasil akhirnya ke:

```text
zf_live_learning/
```

Data ini dipakai untuk:

- Mengukur akurasi proyeksi ZF.
- Menghitung expectancy.
- Memperbarui optimizer.
- Menahan pair atau setup yang performanya memburuk.

Semakin lama scanner berjalan dengan data yang cukup, semakin banyak bahan kalibrasi yang tersedia. Namun, peningkatan winrate tidak pernah bisa dijamin linear karena kondisi market berubah.

## Mode Data Provider

### MT5

Mode utama untuk Windows dengan terminal MetaTrader 5.

```text
ZF_DATA_PROVIDER=MT5
```

Kelebihan:

- Data sesuai broker.
- Mendukung bid/ask dan informasi symbol broker.
- Cocok untuk penggunaan lokal.

### YFINANCE

Mode alternatif tanpa MT5.

```text
ZF_DATA_PROVIDER=YFINANCE
```

Kelebihan:

- Tidak butuh terminal MT5.
- Mudah dipakai di Docker/NAS.
- Gratis.

Keterbatasan:

- Data tidak identik dengan broker.
- Tidak memiliki order book asli.
- Spread dan liquidity memakai proksi.
- Lebih cocok untuk scanner pembelajaran, bukan eksekusi presisi broker.

## Catatan Risiko

Trading memiliki risiko tinggi. Scanner ini tidak menjamin profit. Seluruh sinyal harus dipahami sebagai bahan pertimbangan, bukan perintah mutlak.

Pengguna disarankan:

1. Mulai dari akun demo.
2. Catat setiap sinyal dan hasilnya.
3. Jangan menaikkan lot sebelum data learning cukup.
4. Hindari entry saat news besar.
5. Selalu jaga disiplin risiko.

## Penutup

ZF Core Scanner adalah ikhtiar untuk membaca pasar dengan disiplin, adab, dan struktur. Ia tidak menggantikan kebijaksanaan manusia. Ia hanya membantu menata data agar pengguna tidak terbawa emosi pasar.

Jaga ibadahmu. Jaga adabmu. Jaga risikomu.
