# PadTV-Store

Modulární poskytovatelé aplikací PadTV. Spusťte `python -m padtv_store.cli status`.

Qt adaptér je v `integration/store_ui.py` a používá rozhraní hostitele PadTV OS. Katalog je při vydání převzatý z PadTV-Apps. GitHub poskytovatel stahuje APK z konkrétního Release; před instalací ověřuje schválenou velikost, SHA-256, podpis a identitu balíčku.

[PadBridge — experimentální Android kompatibilita](https://github.com/PadTVos/PadBridge).
