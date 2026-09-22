# Локальный справочник лекарственных средств

Справочник отделён от пользовательской SQLite БД дневника и работает на PostgreSQL 15+.

## Переменные окружения

- `DRUG_DB_DSN` — строка подключения приложения и загрузчика.
- `GRLS_EXPORT_URL` — конкретный URL актуальной выгрузки ГРЛС (ZIP/XLSX).
- `MDLP_EXPORT_URL` — конкретный URL актуальной CSV-выгрузки Датамаркета.
- `DRUGDB_UPDATE_INTERVAL_SECONDS` — период синхронизации, по умолчанию 86400.

URL выгрузок не зашиваются в образ: государственные порталы могут менять адреса файлов.

## Запуск вручную

```bash
python drugdb/loader.py grls --file ./grls.zip
python drugdb/loader.py mdlp --file ./mdlp.csv
```

Проверка:

```sql
SELECT d.trade_name, d.reg_number, g.gtin
FROM drug_gtins g JOIN drugs d ON d.id=g.drug_id
WHERE g.gtin='04601234567890';
```

Для production URL выгрузки задаются в `.env`; секреты и пароли в Git не хранятся.
