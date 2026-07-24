# Kotłownia 2.0

Lokalny sterownik kotłowni dla Raspberry Pi. Automatyka działa niezależnie od panelu WWW i Internetu.

## Zaimplementowana logika

- pompa ładująca bojler uruchamia się, gdy temperatura rury osiągnie skonfigurowany próg,
- domyślny próg wynosi `45°C`,
- pompa pracuje przez skonfigurowany czas, domyślnie `600 s` (10 minut),
- po zakończeniu pracy kolejne sprawdzenie możliwości ładowania następuje po skonfigurowanej przerwie, domyślnie `3600 s` (1 godzina),
- grzałka elektryczna nigdy nie może pracować równocześnie z pompą ładującą,
- żądanie pracy grzałki jest przygotowane jako wejście dla przyszłego harmonogramu lub API; domyślnie jest wyłączone,
- niski poziom pelletu ustawia alarm w stanie sterownika i może wysłać e-mail,
- błąd czujnika przełącza automat w stan `ERROR`, wyłącza pompę ładującą i grzałkę.


## Architektura aplikacji

- `controller/main.py` jest cienkim punktem startowym CLI i obsługuje sygnały systemd,
- `controller/application.py` wykonuje cykle odczyt → decyzja → wyjścia → zapis,
- `controller/automation.py` zawiera wyłącznie deterministyczne reguły sterowania,
- `controller/events.py` rozsyła lokalne zdarzenia bez zależności od Internetu,
- `controller/history.py` zapisuje pomiary i zdarzenia w SQLite.

## Historia SQLite

Historia jest domyślnie włączona:

```toml
[history]
enabled = true
database_file = "runtime/history.db"
sample_interval_seconds = 10.0
```

`state.json` nadal zawiera najnowszy stan. `history.db` przechowuje pomiary w tabeli
`measurements` i zdarzenia w tabeli `events`. Zapis co 10 sekund ogranicza liczbę
zapisów na karcie pamięci, niezależnie od częstotliwości głównej pętli.

Szybkie sprawdzenie liczby rekordów bez instalowania klienta SQLite:

```bash
python - <<'PYSQL'
import sqlite3

with sqlite3.connect("runtime/history.db") as db:
    print("Pomiary:", db.execute("SELECT COUNT(*) FROM measurements").fetchone()[0])
    print("Zdarzenia:", db.execute("SELECT COUNT(*) FROM events").fetchone()[0])
PYSQL
```

Obecnie rejestrowane zdarzenia:

- niski poziom pelletu i powrót do prawidłowego poziomu,
- pierwszy błąd sterownika i powrót do prawidłowej pracy.

## Diagnostyka HC-SR04

Pojedynczy brak echa nie zatrzymuje sterownika. Każdy cykl pobiera serię próbek,
a pomiar jest uznawany za poprawny po uzyskaniu wymaganej minimalnej liczby próbek:

```toml
[pellet]
sample_count = 5
minimum_valid_samples = 3
max_consecutive_failures = 5
```

Jeżeli cała seria jest nieudana, sterownik tymczasowo używa ostatniego poprawnego
poziomu pelletu i ustawia w `state.json` pola `pellet_sensor_stale = true` oraz
`pellet_sensor_consecutive_failures`. Dopiero piąty kolejny nieudany cykl powoduje
stan bezpieczny `ERROR`. Pierwszy poprawny odczyt zeruje licznik.

## Konfiguracja automatyki

```toml
[automation]
boiler_loading_temperature_c = 45.0
boiler_loading_seconds = 600
boiler_loading_recheck_seconds = 3600
pellet_low_level_percent = 15.0
pellet_low_reminder_seconds = 86400
```

`pellet_low_reminder_seconds` ogranicza liczbę wiadomości przy stale niskim poziomie pelletu. Domyślnie przypomnienie może zostać wysłane raz na dobę.

## Powiadomienia e-mail

Domyślnie wysyłanie wiadomości jest wyłączone:

```toml
[email_notifications]
enabled = false
smtp_host = "smtp.example.com"
smtp_port = 587
use_starttls = true
username_env = "KOTLOWNIA_SMTP_USERNAME"
password_env = "KOTLOWNIA_SMTP_PASSWORD"
sender = "kotlownia@example.com"
recipient = "adres@example.com"
```

Hasła nie są przechowywane w repozytorium. Przed uruchomieniem usługi ustaw zmienne środowiskowe:

```bash
export KOTLOWNIA_SMTP_USERNAME='login'
export KOTLOWNIA_SMTP_PASSWORD='haslo-aplikacji'
```

Następnie wpisz prawidłowe dane serwera SMTP, nadawcę i odbiorcę oraz ustaw:

```toml
enabled = true
```

## Instalacja na Raspberry Pi

```bash
cd /home/eddy/Kotlownia2
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

Plik `requirements-dev.txt` instaluje również zależności sprzętowe z `requirements.txt`, w tym `gpiozero` i backend `lgpio` dla HC-SR04 oraz przekaźników.

Do uruchomienia bez narzędzi testowych wystarczy:

```bash
python -m pip install -r requirements.txt
```

## Testy

```bash
pytest
python -m controller.main --once
cat runtime/state.json
```

Uruchomienie ciągłe:

```bash
python -m controller.main
```

Zatrzymanie: `Ctrl+C`.

## Tryb sprzętowy

`application.simulation` steruje wyjściami przekaźników. Czujniki mają własne flagi `simulation`.
Przed fizycznym włączeniem wyjść sprawdź poziomy logiczne modułu przekaźników oraz zabezpieczenia elektryczne grzałki i pomp.

## Instalacja jako usługa systemd

Najpierw wykonaj test pojedynczego cyklu z przekaźnikami w symulacji:

```bash
cd /home/eddy/Kotlownia2
source .venv/bin/activate
pytest
python -m controller.main --once
```

Sprawdzenie samej konfiguracji nie inicjalizuje GPIO:

```bash
python -m controller.main --check-config
```

Instalacja usługi:

```bash
cd /home/eddy/Kotlownia2
./scripts/install_service.sh
sudo systemctl start kotlownia.service
systemctl status kotlownia.service
```

Podgląd logów na żywo:

```bash
journalctl -u kotlownia.service -f
```

Zatrzymanie i ponowne uruchomienie:

```bash
sudo systemctl stop kotlownia.service
sudo systemctl restart kotlownia.service
```

Usługa uruchamia się automatycznie po restarcie Raspberry Pi. Instalator sam wpisuje aktualnego użytkownika i katalog projektu do pliku systemd.

Dane SMTP przechowuj w `config/kotlownia.env`, który jest pomijany przez Git. Wzór znajduje się w `config/kotlownia.env.example`.

## Bezpieczne uruchamianie

Na tym etapie pozostaw:

```toml
[application]
simulation = true
```

Czujniki DS18B20 i HC-SR04 działają realnie, ale przekaźniki nie są fizycznie przełączane. Tryb sprzętowy wyjść włączymy dopiero po sprawdzeniu usługi przez dłuższą pracę w symulacji i osobnym teście każdego przekaźnika.

## Zmiany w wersji 0.2.3

- Przekaźniki wykonują operację GPIO tylko wtedy, gdy żądany stan różni się od ostatnio zastosowanego.
- Logi przekaźników pokazują wyłącznie rzeczywiste przejścia stanu.
- Pierwsza inicjalizacja nadal wymusza pełny bezpieczny stan wyjść.
- `close()` jest bezpieczne przy wielokrotnym wywołaniu.
- Zachowana jest blokada jednoczesnej pracy pompy ładującej i grzałki.

## Harmonogram i panel WWW — wersja 0.3.0

Sterownik odczytuje harmonogram z `runtime/schedule.json`. Plik jest zapisywany
atomowo przez panel WWW i odczytywany przez sterownik w każdym cyklu. Dzięki temu
panel nie steruje GPIO bezpośrednio — jedynie przekazuje żądanie do istniejącej
automatyki i jej zabezpieczeń.

Obsługiwane są osobne okna dla:

- pompy cyrkulacyjnej CWU,
- grzałki elektrycznej.

Okna mają godzinę rozpoczęcia, zakończenia i wybrane dni tygodnia. Mogą przechodzić
przez północ. Strefa czasowa domyślnie to `Europe/Warsaw`.

Panel lokalny uruchamia się jako osobna usługa `kotlownia-web.service` na porcie
`8088`. Awaria lub restart WWW nie zatrzymuje głównego sterownika.

Po instalacji:

```bash
sudo systemctl restart kotlownia.service kotlownia-web.service
systemctl status kotlownia.service kotlownia-web.service
```

Panel otwórz w sieci lokalnej:

```text
http://ADRES_IP_RASPBERRY:8088
```

Nie przekierowuj portu `8088` na routerze. Pierwsza wersja panelu jest przeznaczona
wyłącznie do zaufanej sieci LAN i nie ma jeszcze logowania użytkowników.

Grzałka ma harmonogram domyślnie wyłączony. Nie włączaj jej czasowo, dopóki nie
potwierdzimy niezależnego termostatu, zabezpieczenia nadtemperaturowego i poprawnego
okablowania stycznika. Harmonogram cyrkulacji CWU można bezpiecznie testować nadal
w trybie `simulation = true`.

Przy aktualizacji z wcześniejszej paczki zachowaj bazę historii i plik stanu:

```bash
./scripts/migrate_runtime.sh ~/Kotlownia2-v7-backup
```

Przykładowy harmonogram znajduje się w `config/schedule.example.json`.
