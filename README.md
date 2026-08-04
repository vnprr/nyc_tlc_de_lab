# NYC TLC Trip Data Pipeline

Edukacyjny pipeline danych dla kursów NYC Yellow Taxi i godzinowej pogody w
Nowym Jorku. Projekt przygotowuje dane do późniejszego modelu wymiarowego, ale
na obecnym etapie skupia się na jakości, partycjonowaniu i prostym incremental
load.

## Co buduje projekt

```text
NYC TLC Parquet -> raw taxi -> processed / rejected / quality
Open-Meteo JSON -> raw weather -> processed weather
processed taxi + processed weather -> hourly analytics
```

Warstwy mają różne zadania:

- `raw` zachowuje dane źródłowe;
- `processed` normalizuje schemat i dodaje flagi jakości;
- `rejected` zawiera wyłącznie rekordy bez wiarygodnego pickup time;
- `reports` przechowuje reconciliation i liczniki jakości;
- `analytics` agreguje kursy do jednej lokalnej godziny i dołącza pogodę.

## Najważniejsze decyzje

### Taxi

- Domyślnie przetwarzane są tylko miesiące z `NYC_LAKE_MONTHS`.
- Raw taxi jest chroniony SHA-256. Ten sam klucz z inną treścią zatrzymuje krok.
- Schemat źródła zależy od okresu: v1 do 2024-12, v2 od 2025-01.
- Transformacja używa stałego okna
  `[początek miesiąca - 7 dni, koniec miesiąca + 7 dni)`.
- Wynik nie zależy od dnia uruchomienia.
- Obowiązuje `raw_rows = processed_rows + rejected_rows`.
- Rekordy mają lineage `(source_file, source_row_number)`.
- Pełne duplikaty zostają zachowane i są flagowane.
- Strefy 264 `Unknown` i 265 `Outside NYC` mają oddzielne flagi.
- Czas przejazdu jest liczony pomiędzy chwilami UTC.
- Niejednoznaczne i nieistniejące lokalne czasy DST nie są zgadywane. Rekord
  zostaje, ale jego `duration` i `speed` są puste.

Pełny kontrakt znajduje się w
[docs/table_of_cleansing.md](docs/table_of_cleansing.md).

### Manifest taxi

Manifest rozwiązuje dwa proste problemy:

1. nie przeliczamy ponownie aktualnego źródła;
2. przerwany zapis nie może wyglądać jak zakończony.

Ma tylko dwa stany:

```text
processing -> complete
```

Skip jest możliwy, gdy:

- ETag raw jest aktualny;
- `TRANSFORM_VERSION` jest aktualny;
- row counts każdego processed i rejected outputu sumują się do wyniku źródła;
- wszystkie zadeklarowane outputy istnieją.

Po udanym zapisie pipeline wyszukuje pod zarządzanym prefixem wszystkie stare
partycje z nazwą bieżącego źródła i usuwa te, których nowy run nie utworzył.
Dzięki temu rebuild v3 usuwa również outputy dawnej, szerszej polityki dat.
Prefixy `processed/`, `rejected/`, `reports/` i `analytics/` są zarządzane przez
pipeline. Ręczne backupy nie powinny się w nich znajdować.

Projekt zakłada jednego autora zapisów. Nie ma locka ani obsługi równoległych
runów tego samego kroku.

### Pogoda

- Request jawnie ustala strefę, jednostki i format czasu.
- Payload jest walidowany przed zapisaniem do raw.
- Musi zawierać dokładnie jedną nominalną godzinę dla każdej godziny miesiąca.
- Raw używa jednego deterministycznego klucza na miesiąc.
- Normalny run go nie nadpisuje. `--force` robi to świadomie.
- Manifest zapisuje SHA-256 raw, a krok `06` sprawdza go przed transformacją.
- Processed weather jest mały, więc jest zawsze przeliczany od nowa.
- Parquet zapisuje w metadata hash raw i wersję transformacji pogody.
- Krok `07` porównuje te metadata z aktualnym manifestem raw przed użyciem
  pogody.

Historia wersji raw weather powinna docelowo wynikać z S3 Versioning, a nie z
własnego systemu snapshotów w Pythonie.

### Analytics

- Ziarno wyniku to jedna lokalna godzina pickup.
- Zapisywane są sumy i liczniki, więc wyższe agregacje nie muszą uśredniać
  średnich.
- Wadliwe metryki czasu są wykluczane, ale kurs nadal jest liczony jakościowo.
- Join z pogodą wymaga relacji `one_to_one` i nie pozwala na brakujące godziny.
- Każdy wczytany kurs musi należeć do event month wynikającego z partycji.
- Event month `M` wymaga źródeł taxi `M-1`, `M` i `M+1`.

Przy domyślnych źródłach styczeń-marzec publikowalny jest tylko luty. Aby
opublikować cały styczeń-marzec, zakres źródłowy musi obejmować grudzień-kwiecień.

## Konfiguracja

```bash
uv sync
cp .env.example .env
```

| Zmienna | Znaczenie |
| --- | --- |
| `NYC_LAKE_BUCKET` | Wymagany bucket S3 dla kroków AWS |
| `NYC_LAKE_WORKDIR` | Katalog plików tymczasowych |
| `NYC_LAKE_RAW_DIR` | Lokalny cache NYC TLC |
| `NYC_LAKE_MONTHS` | Rosnąca lista źródeł `YYYY-MM` |

Ścieżki względne są rozwiązywane względem katalogu projektu.

## Uruchamianie

```bash
uv run python 01_download_raw.py
uv run python 02_profile_source.py --month 2024-01
uv run python 03_upload_raw_to_s3.py
uv run python 04_clean_to_processed.py
uv run python 05_ingest_weather.py
uv run python 06_process_weather.py
uv run python 07_build_analytics.py
```

Przydatne opcje:

```bash
uv run python 04_clean_to_processed.py --only 2024-02
uv run python 04_clean_to_processed.py --force
uv run python 05_ingest_weather.py --force
```

## Układ S3

```text
raw/yellow_taxi/yellow_tripdata_YYYY-MM.parquet
raw/weather_hourly/weather_YYYY-MM.json

processed/yellow_taxi/year=YYYY/month=MM/yellow_tripdata_YYYY-MM.parquet
processed/weather_hourly/year=YYYY/month=MM/weather_YYYY-MM.parquet

rejected/yellow_taxi/yellow_tripdata_YYYY-MM.parquet
reports/yellow_taxi/yellow_tripdata_YYYY-MM_quality.csv
analytics/trips_weather_hourly/year=YYYY/month=MM/trips_weather_YYYY-MM.parquet

_meta/yellow_taxi_manifest.json
_meta/weather_manifest.json
```

## Testy

```bash
uv run pytest -q
uv run ruff check 0*.py src tests
uv run ruff format --check 0*.py src tests
```

Testy S3 korzystają z atrap i nie zapisują do prawdziwego AWS.

## Świadome ograniczenia

- Brak orchestratora, retry policy i blokady równoległych runów.
- Brak atomowej publikacji wielu obiektów S3.
- Brak wersjonowanych definicji Glue/Athena.
- Lokalna godzina jesiennego DST nadal nie jest unikalnym kluczem analytics.
- Analytics nie ma jeszcze własnego manifestu publikacji.
- Pipeline ładuje cały miesiąc do pamięci Pandas.
- Nie ma jeszcze `dim_zone`, `dim_time` ani docelowego `fact_trip`.

Aktualny audyt i pozostałe zadania znajdują się w
[docs/audit_and_remediation.md](docs/audit_and_remediation.md).
