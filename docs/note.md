# 04. Przejście z full refresh na incremental load

Nie możemy opierać przetwarzania na samym fakcie czy plik istnieje czy nie - bo nie wiemy jaki będzie output pipeline'u.

Dlatego potrzebujemy pliku stanu.

> [!IMPORTANT] Relacja wejście-wyjście a stan pipeline'u
> `skip-if-exists` nadaje się tylko dla niezmiennych wejść 1:1
> natomiast gdy zachodzi relcja wejście:wyjście 1:N potrzebujemy plik stanu.

## Projekt manifestu

Manifest znajdzie się w:

`s3;// ... /_meta/yellow_taxi_manifest.json`

JSON z prefiksem `_meta` jest pomijany przez Spark.

Zapis JSON'a do S3 nie jest transakcyjny (ostatni zapisujący nadpisuje), możemy więc ewentualnie albo oddać go orkiestratorowi, albo stanowi w bazie danych.

Manifest może też rozjechać się z rzeczywistością S3 (np. ktoś ręcznie skasuje partycję), dlatego istnieje pojęcie reconciliation i dodajemy flagę --force.

# 05. Poprawa walidacji

Z dniem 5.01.2025 TLC wprowadziło dodatkową kolumnę `cbd_congestion_fee`. 

Dlatego pipeline na tych danych zatrzyma się.

## Obsługa ewolucji schematu

Schmaty reakcji na drift:

- FAIL LOUDLY - zatrzymaj, człowiek decyduje
- IGNORE - przetwarzaj znane, nowe pomijaj
- AUTO-EVOLVE - przyjmij nowe. Wygodne ale nieprzewidywalne (Fivetran, Airbyte, Delta Lake z schema evolution)

## Implementacja obsługi schematu

### `validate.py`

```Python
SCHEMA_V1 = REQUIRED_COLUMNS
SCHEMA_V2 = SCHEMA_V1 | {"cbd_congestion_fee"} # unia zbiorów
KNOWN_SCHEMAS = {
    "v1_through_2024" : SCHEMA_V1,
    "v2_from_2025_01" : SCHEMA_V2
}
```

Teraz pipeline sprawdza dopasowanie do schematu.

### `transform.py`

# 06. Drugie źródło: pogoda i join


# 08. Athena

## Co to jest

Athena to hurtownia danych, ale niejako odwracająca klasyczny układ:

`budowa hurtowni -> załadowanie danych (ETL)`

Zamiast nosić dane do silnika, Athena "przynosi silnik do danych" i pozwala na korzystanie z plików S3 jak z RBD. 

Tym samym Atena rozdziela silnik od danych, tzw. ***"Separation of storage and compute"***.

Dzięki temu dane leżą tanio w s3 i różne narzędzia mogą je czytać:
- dziś Athena,
- jutro Spark,
- a pojutrze jakiś nowy silnik.

## Architektura

### Silnik

Pod maską siedzi Trino (dawniej Presto) - open-source'owy rozproszony silnik SQL.

### Dialekt SQL

Dialekt Atheny to Trino: standardowy SQL plus funkcje typu `date_trunc`, `approx_distinct`

### Serverless

Nie ma żadnego włączanego i wyłączanego klastra. Zapytanie idzie do usługi, AWS je obsługuje i zwraca wynik.

### Schema-on-read

Dane w plikach pozostają nietknięte, schemat jest nakładany przy odczycie.

## Model rozliczeń

Athena kosztuje 5USD za 1TB przeskanowanych danych (minimum 10MB za zapytanie). Płaci się za przetworzone dane a nie za czas stania serwera. 

To wymaga specjalnej inżynierii, która optymalizuje nie czas, ale wielkość obliczeń. 

- partycje pozwalają silnikowi pominąć całe foldery
- Parquet dzięki formatowi kolumnowemu pozwala czytać tylko potrzebne kolumny.

### Athena vs hurtownia

| - | Athena (lake + SQL) | Hurtownia (Snowflake / Redshift / BigQuerry) |
| --- | --- | --- |
| Przeznaczenie | ad-hoc analizy na lake'u. Rzadkie zapytania, eksploracja, tanie archiwum | setki zapytań dziennie, dashboardy BI, wielu użytkowników naraz, gdy jest wymagana niska latencja |
| Koszt  | tylko za stan, zero kosztów danych | kosz stały (klastry), opłacalne tylko przy stałym ruchu |
| Wydajność | sekundy / minuty (brak indeksów) | zoptymalizowane pod powtarzalne obciążenia (indeksy, cache) |
| Dane | zostają w s3, otwarte formaty | zwykle ładowane do silnika (model ewoluuje) |

To nie jest kwestia "albo", zwykle używa się obu.

## `Glue Data Catalog`: spis treści lake'a 
Athena gdzieś musi przechowywać informacje "co jest gdzie". 

AWS Glue Data Catalog to centralny rejestr metadanych.

Jego hierarchia jest 3-poziomowa:
- Database - folder na tabele
- Table - schemat kolumn + format plików + lokalizacja w s3
- Partition - wpis typu "partycja year=2024/month=01 leży pod tym prefixem". Katalog nie wykrywa sam partycji, trzeba mu o tym powiedzieć.

### Dlaczego katalog jest oddzieoną usługą?
Bo z tych samych katalogów korzystają też inne silniki: Spark na EMR, Redshift Spectrum, Glue ETL. Jeden katalog, wielu użytkowników. To znowu część separation of storage and compute.

