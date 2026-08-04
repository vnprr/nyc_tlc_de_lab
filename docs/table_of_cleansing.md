# Kontrakt czyszczenia danych NYC Yellow Taxi

Ten dokument opisuje decyzje wykonywane przez `src/transform.py`. Nie jest listą
pomysłów z EDA. Jest kontraktem: zmiana reguły albo schematu processed wymaga
zmiany `TRANSFORM_VERSION`, testów i przebudowy danych pochodnych. Aktualna
wersja kontraktu to `3.0.0`.

## Zasada nadrzędna

Warstwa `processed` ma zachować prawdę źródłową i dodać informację o jakości.
Nie poprawiamy wartości bez dowodu. Anomalia zwykle dostaje flagę, a konsument
decyduje, czy wykluczyć ją z konkretnej metryki.

Do `rejected` trafia tylko rekord, którego pickup timestamp nie pozwala
wiarygodnie przypisać do zakresu przetwarzania. Dzięki temu:

```text
raw_rows = processed_rows + rejected_rows
```

## 1. Pochodzenie i duplikaty

### Po co

Dwa identyczne wiersze nie muszą oznaczać błędu. Mogą być dwiema osobnymi
transakcjami albo powtórzeniem źródła. Bez stabilnego identyfikatora nie wolno
arbitralnie usuwać jednego z nich.

| Przypadek | Decyzja | Pole |
| --- | --- | --- |
| Każdy rekord | Zachowaj nazwę pliku i pozycję w raw, liczoną od zera | `source_file`, `source_row_number` |
| Pełny duplikat wszystkich oryginalnych kolumn | Zachowaj wszystkie kopie i oznacz każdą z nich | `is_exact_duplicate` |

Klucz technicznego pochodzenia to:

```text
(source_file, source_row_number)
```

W lutym 2024 faktycznie występuje jedna grupa dwóch pełnych duplikatów. Stare
stwierdzenie, że w danych nie ma duplikatów, było błędne.

## 2. Zaufane okno pickup

### Po co

Plik nazwany `2024-02` może zawierać kilka poprawnych rekordów tuż obok granicy
miesiąca. Może też zawierać datę odległą o lata wskutek błędnego zegara. Reguła
nie może zależeć od dnia, w którym uruchomimy pipeline, bo retry dałby inny
wynik.

Dla miesiąca raportowego wyliczamy:

```text
reporting_start = pierwszy dzień miesiąca 00:00
reporting_end   = pierwszy dzień następnego miesiąca 00:00
trusted_start   = reporting_start - 7 dni
trusted_end     = reporting_end + 7 dni
```

Zaufane okno jest lewostronnie domknięte:

```text
[trusted_start, trusted_end)
```

To świadoma zmiana kontraktu v3. Wcześniejsza logika dopuszczała daty nawet rok
przed początkiem miesiąca, a górną granicę wiązała z czasem uruchomienia. Nowa
reguła daje powtarzalny wynik, lecz może odrzucić rekord, który wcześniej został
zachowany.

Próg 7 dni wynika z EDA plików Jan-Mar 2024: sensowne rekordy graniczne leżały
blisko zmiany miesiąca, natomiast 9 odrzuconych timestampów było znacznie
starszych. Nie jest to uniwersalne prawo dla wszystkich danych TLC. Przed
rozszerzeniem zakresu należy ponownie zmierzyć rozkład rekordów granicznych.
Zmiana progu wymaga nowej wersji transformacji i przebudowy warstw pochodnych.

| Przypadek | Decyzja | `rejection_reason` |
| --- | --- | --- |
| Brak pickup timestamp | Przenieś do `rejected` | `missing_pickup_timestamp` |
| Pickup przed `trusted_start` | Przenieś do `rejected` | `pickup_before_trusted_window` |
| Pickup równy lub późniejszy od `trusted_end` | Przenieś do `rejected` | `pickup_after_trusted_window` |
| Pickup w zaufanym oknie, ale poza miesiącem pliku | Zachowaj w `processed` i oznacz | `is_outside_reporting_month` |

`is_outside_reporting_month` opisuje relację do miesiąca pliku źródłowego. Nie
oznacza automatycznie błędu i nie jest regułą odrzucenia.

## 3. Czas kursu

### Po co

Duration i średnia prędkość są wartościami pochodnymi. Jeżeli timestampy są
niewiarygodne, źródłowy rekord nadal może być potrzebny do kontroli finansowej,
ale nie powinien zanieczyszczać metryk czasu i prędkości.

Źródło zapisuje naiwne etykiety lokalnego czasu Nowego Jorku. Nie można ich
odejmować bezpośrednio, bo w marcu doba ma raz 23 godziny, a jesienią raz 25.
Najpierw interpretujemy oba endpointy w `America/New_York`, zamieniamy je na
chwile UTC, a dopiero potem odejmujemy:

```text
pickup_instant_utc  = localize(pickup_datetime, America/New_York)
dropoff_instant_utc = localize(dropoff_datetime, America/New_York)
trip_duration_minutes = dropoff_instant_utc - pickup_instant_utc
average_speed_mph = trip_distance / (trip_duration_minutes / 60)
```

Prędkość liczymy tylko dla `duration > 0` i `distance >= 0`.

| Przypadek | Decyzja | Flaga | Dokładna definicja |
| --- | --- | --- | --- |
| Brak dropoff | Zachowaj, duration i speed pozostają puste | `is_missing_dropoff` | `dropoff_datetime IS NULL` |
| Pickup w powtórzonej jesiennej godzinie | Zachowaj, nie zgaduj fold, duration i speed puste | `is_ambiguous_pickup_datetime` | lokalna etykieta wskazuje dwie chwile UTC |
| Pickup w nieistniejącej wiosennej godzinie | Zachowaj, duration i speed puste | `is_nonexistent_pickup_datetime` | lokalna etykieta nie wskazuje żadnej chwili UTC |
| Dropoff w powtórzonej jesiennej godzinie | Zachowaj, nie zgaduj fold, duration i speed puste | `is_ambiguous_dropoff_datetime` | lokalna etykieta wskazuje dwie chwile UTC |
| Dropoff w nieistniejącej wiosennej godzinie | Zachowaj, duration i speed puste | `is_nonexistent_dropoff_datetime` | lokalna etykieta nie wskazuje żadnej chwili UTC |
| Czas zerowy lub ujemny | Zachowaj, wyklucz z normalnych metryk czasu | `is_nonpositive_duration` | `duration <= 0` |
| Bardzo długi kurs | Zachowaj, wyklucz z normalnych metryk czasu | `is_long_duration` | `360 < duration < 1380` minut |
| Czas bliski 24 godzinom | Zachowaj, wyklucz z normalnych metryk czasu | `is_near_24h_duration` | `1380 <= duration < 1440` minut |
| Co najmniej 24 godziny | Zachowaj, wyklucz z normalnych metryk czasu | `is_over_24h_duration` | `duration >= 1440` minut |
| Prędkość większa niż 80 mph | Zachowaj, wyklucz z normalnych metryk czasu | `is_implausible_speed` | `average_speed_mph > 80` |

W jesiennej powtórzonej godzinie raw nie zawiera offsetu UTC ani znacznika
`fold`. `ambiguous=True` zawsze wybrałoby pierwsze wystąpienie godziny, a
`ambiguous=False` drugie. Obie reguły mogą przesunąć rzeczywisty czas kursu o
60 minut. `ambiguous="infer"` wymaga odpowiednio uporządkowanej sekwencji, której
nie gwarantują niezależne kolumny pickup i dropoff.

Kontrakt v3 świadomie wybiera `NaT`. Rekord nie jest usuwany. Dostaje flagę i
pozostaje dostępny dla metryk niezależnych od czasu, ale jego duration i speed
nie są liczone. Zyskiem jest brak wymyślonej chwili UTC. Kosztem jest mniejsze
pokrycie metryk w powtórzonej godzinie. Ten koszt musi być raportowany. Zmiana
na heurystykę wymaga pomiaru jej błędu, nowej wersji transformacji i rebuildu.

Zakres od 0 do 360 minut włącznie nie dostaje flagi `is_long_duration`. Dokładnie
1380 minut należy już do `is_near_24h_duration`, a dokładnie 1440 minut do
`is_over_24h_duration`.

Na pełnym marcu 2024 ta poprawka skróciła 1 153 duration o dokładnie 60 minut.
Trzy dropoffy wskazywały nieistniejącą lokalną godzinę i dlatego mają puste
duration oraz speed zamiast zgadywanej wartości.

## 4. Dystans

| Przypadek | Decyzja | Flaga |
| --- | --- | --- |
| Dystans ujemny | Zachowaj, wyklucz z normalnych metryk czasu i dystansu | `is_negative_distance` |
| Dystans równy zero | Zachowaj i monitoruj, ale nie wykluczaj tylko z tego powodu | `is_zero_distance` |
| Dystans większy niż 100 mil | Zachowaj, wyklucz z normalnych metryk czasu i dystansu | `is_extreme_distance` |

Zero może opisywać anulowany kurs, opłatę bez przejazdu albo błąd pomiaru. Sama
wartość zero nie daje wystarczającego dowodu do usunięcia rekordu.

## 5. Pasażerowie

| Przypadek | Decyzja | Flaga |
| --- | --- | --- |
| Brak liczby pasażerów | Zachowaj brak, nie uzupełniaj zerem ani jedynką | `is_missing_passenger_count` |
| Wartość ujemna | Zachowaj i oznacz | `is_negative_passenger_count` |
| Wartość zero | Zachowaj i oznacz | `is_zero_passengers` |
| Wartość większa niż 6 | Zachowaj i oznacz | `is_high_passenger_count` |

Brak i zero to różne informacje. Nie wolno ich łączyć w jedną kategorię.

## 6. Strefy TLC

Oficjalny słownik stref rozróżnia:

| ID | Znaczenie | Flaga, gdy PU albo DO ma tę wartość |
| ---: | --- | --- |
| 264 | `Unknown` | `has_unknown_zone` |
| 265 | `Outside of NYC` | `has_outside_nyc_zone` |

Obie wartości pozostają w danych. Nie wolno nazywać 265 strefą nieznaną, bo
oznacza znaną kategorię poza Nowym Jorkiem.

## 7. Opłaty i kody domenowe

| Przypadek | Decyzja | Flaga |
| --- | --- | --- |
| `payment_type == 0` | Zachowaj braki charakterystyczne dla Flex Fare | `is_flex_fare_record` |
| `ratecode_id == 99` | Zachowaj udokumentowaną kategorię | `is_unknown_ratecode` |
| `total_amount < 0` | Zachowaj znak, nie używaj wartości bezwzględnej | `is_negative_transaction` |
| Znaki `fare_amount` i `total_amount` są różne | Zachowaj i oznacz | `is_amount_sign_mismatch` |
| Total nie zgadza się z prostą sumą komponentów | Nie modyfikuj rekordu, raportuj residual per vendor | metryki jakości vendora |

Nietypowa wartość kodu domenowego jest problemem konkretnego rekordu, a nie
automatycznie uszkodzonym schematem całego pliku. Walidacja ją raportuje, lecz
nie zatrzymuje batcha, jeśli fizyczny schema i typy są poprawne.

## 8. Ewolucja schematu

| Okres źródła | Oczekiwany schema | `cbd_congestion_fee` w processed |
| --- | --- | --- |
| do 2024-12 | v1, bez kolumny CBD | dodane `0.0` jako neutralny składnik |
| od 2025-01 | v2, z kolumną CBD | zachowana wartość źródłowa |

Plik musi pasować dokładnie do wersji wymaganej dla swojego miesiąca. Dzięki
temu kolumna nie może pojawić się za wcześnie ani zniknąć po dacie wdrożenia.
Każda niepusta wartość numeryczna musi być skończona. `NaN` pozostaje
dozwolonym brakiem danych, ale `+inf` i `-inf` są błędem fizycznego kontraktu
pliku i zatrzymują przetwarzanie.

## 9. Raport jakości

Raport CSV ma kolumny:

| Kolumna | Znaczenie |
| --- | --- |
| `metric` | stabilna nazwa metryki |
| `value` | wartość metryki |
| `unit` | `rows`, `usd` albo `percent` |
| `percentage_of_raw` | udział raw tylko tam, gdzie ma sens |

Nie używamy jednej kolumny `count` do mieszania liczby wierszy, dolarów i
procentów.

## Pułapki

- Nie usuwaj wszystkich rekordów poza miesiącem pliku. Część to poprawne dane
  graniczne, które trafią do partycji zgodnej z event time.
- Nie deduplikuj po wszystkich kolumnach bez klucza biznesowego i reguły
  zatwierdzonej przez właściciela danych.
- Nie licz średniej z już policzonych średnich godzinowych. Użyj sum i
  mianowników przechowywanych w analytics.
- Nie zmieniaj progu flagi bez zmiany wersji transformacji i przebudowy danych.
- Nie mieszaj starych partycji processed z nowym schematem.
- Nie odejmuj bezpośrednio naiwnych timestampów lokalnych przez granicę DST.

## Sprawdź się

Dla rekordu z pickup `2024-01-31 23:58`, dropoff `2024-02-01 00:08`, dystansem
`0` i `passenger_count = NULL` oczekiwany wynik to:

```text
processed: tak
is_outside_reporting_month: false dla pliku 2024-01
trip_duration_minutes: 10
is_zero_distance: true
is_missing_passenger_count: true
is_implausible_speed: false
```

Dla tego samego rekordu w pliku `2024-02` zmieni się wyłącznie znaczenie
lineage: `is_outside_reporting_month` będzie `true`. Rekord nadal pozostanie w
processed, bo mieści się w siedmiodniowym zaufanym oknie lutego.

Dla pickup `2024-03-10 01:30` i dropoff `2024-03-10 03:30` oczekiwane duration
to 60, a nie 120 minut. Zegar lokalny przeskoczył z `01:59:59` na `03:00:00`.
