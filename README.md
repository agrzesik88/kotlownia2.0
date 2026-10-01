# Kotłownia 2.0

Lokalny sterownik kotłowni dla Raspberry Pi. Automatyka działa niezależnie od panelu WWW i Internetu.

Projekt steruje czterema wyjściami przekaźnikowymi, monitoruje temperaturę kotła/rury oraz poziom pelletu i zapisuje historię pracy w SQLite.

## Aktualne funkcje

- automatyczne sterowanie pompą ładującą bojler na podstawie temperatury,
- automatyczna cyrkulacja CWU z harmonogramu,
- harmonogram dla dodatkowego wyjścia,
- niezależne włączanie/wyłączanie każdego zakresu harmonogramu,
- ręczne sterowanie z panelu WWW z automatycznym wygasaniem,
- ręczne sterowanie pompą bojlera i zasilaniem pieca pelletowego,
- pomiar temperatury przez DS18B20,
- pomiar poziomu pelletu przez HC-SR04,
- filtrowanie i tolerancja zmian poziomu pelletu,
- bezpieczna obsługa chwilowych błędów czujników,
- alarmy i powiadomienia e-mail,
- historia pomiarów i zdarzeń w SQLite,
- lokalny panel WWW,
- tryb symulacji oraz rzeczywiste sterowanie GPIO,
- usługa systemd uruchamiana automatycznie po starcie Raspberry Pi.

## Wyjścia GPIO

| Wyjście | GPIO | Opis |
|---|---:|---|
| cwu_circulation | 6 | pompa cyrkulacyjna CWU |
| boiler_loading | 13 | pompa ładująca bojler |
| other | 19 | dodatkowe wyjście |
| pellet_boiler_power | 26 | zasilanie pieca pelletowego |

Przekaźniki są skonfigurowane jako **active-LOW**.

## Automatyka

Domyślne ustawienia:

    [automation]
    boiler_loading_temperature_c = 45.0
    boiler_loading_seconds = 600
    boiler_loading_recheck_seconds = 3600
    pellet_low_level_percent = 15.0
    pellet_low_reminder_seconds = 7200

Pompa ładująca bojler może być uruchamiana automatycznie po osiągnięciu skonfigurowanej temperatury. Czas pracy i odstęp do kolejnego sprawdzenia są konfigurowalne.

Parametry automatyki mogą być zmieniane również z panelu WWW. Zapis trafia do:

    runtime/automation_settings.json

Sterownik odczytuje te ustawienia podczas kolejnych cykli pracy.

### Wyjścia

Sterowanie wyjściami przechodzi przez AutomationController, który odpowiada za reguły bezpieczeństwa.

Pompa bojlera i dodatkowe wyjście mogą działać niezależnie.

W przypadku błędu sterownika wykonywany jest stan bezpieczny:
- cyrkulacja CWU: OFF,
- pompa bojlera: OFF,
- dodatkowe wyjście: OFF,
- zasilanie pieca pelletowego: ON.

## Poziom pelletu

HC-SR04 wykonuje serię pomiarów zgodnie z konfiguracją:

    [pellet]
    trigger_gpio = 23
    echo_gpio = 24
    empty_distance_cm = 57.0
    full_distance_cm = 8.9
    sample_count = 7
    minimum_valid_samples = 5
    max_consecutive_failures = 5
    sample_interval_seconds = 0.05
    level_tolerance_percent = 0.5

Z każdej serii odrzucane są skrajne poprawne pomiary, a następnie wyliczana jest mediana.

Dodatkowo poziom jest wygładzany na podstawie ostatnich 5 wyników. Zmiana mniejsza lub równa 0.5 punktu procentowego jest traktowana jako tolerancja i nie powoduje zmiany zapisanego poziomu.

Chwilowy błąd pomiaru nie zatrzymuje sterownika. Używany jest ostatni poprawny poziom, a w stanie sterownika pojawiają się:
- pellet_sensor_stale,
- pellet_sensor_consecutive_failures.

Po 5 kolejnych nieudanych cyklach sterownik przechodzi do stanu ERROR.

Przy niskim poziomie pelletu generowany jest alarm oraz wysyłane jest powiadomienie e-mail. Przy utrzymującym się niskim poziomie kolejne przypomnienia są ograniczone czasowo.

## Temperatura DS18B20

Czujnik temperatury jest odporny na pojedyncze błędne odczyty.

Po chwilowym błędzie sterownik:
- zachowuje ostatnią poprawną temperaturę,
- zwiększa licznik kolejnych błędów,
- oznacza odczyt jako nieaktualny.

Po przekroczeniu skonfigurowanej liczby kolejnych błędów sterownik przechodzi do stanu bezpiecznego ERROR.

## Harmonogram

Harmonogram jest przechowywany w:

    runtime/schedule.json

Strefa czasowa: Europe/Warsaw.

Obsługiwane są osobne harmonogramy dla:
- cyrkulacji CWU,
- dodatkowego wyjścia.

Każdy zakres posiada:
- godzinę rozpoczęcia,
- godzinę zakończenia,
- dni tygodnia,
- czas trwania pojedynczego uruchomienia,
- czas do ponownego uruchomienia,
- własny przełącznik aktywności.

Zakres może przechodzić przez północ. Zakres start = end oznacza pełne 24 godziny z powtarzaniem zgodnie z konfiguracją.

Panel zapisuje harmonogram atomowo, a sterownik odczytuje go w każdym cyklu.

### Status ostatniego uruchomienia CWU

Panel pokazuje ostatnie uruchomienie cyrkulacji CWU przez harmonogram:
- datę i godzinę rozpoczęcia,
- rzeczywisty czas działania.

Informacja jest zapisywana jako zdarzenia w historii SQLite.

## Sterowanie ręczne

Panel WWW pozwala ręcznie sterować:
- cyrkulacją CWU,
- dodatkowym wyjściem,
- pompą ładującą bojler,
- zasilaniem pieca pelletowego.

Każde żądanie ma czas wygaśnięcia. Po jego upływie sterownik automatycznie wraca do automatyki i harmonogramu.

Plik sterowania:

    runtime/manual_control.json

Konfiguracja:

    [manual_control]
    enabled = true
    command_file = "runtime/manual_control.json"

Panel WWW nie przełącza GPIO bezpośrednio. Wszystkie żądania przechodzą przez główny sterownik i jego automatykę.

## Panel WWW

Panel działa jako osobna usługa:

    kotlownia-web.service

Domyślny port:

    8088

Adres:

    http://ADRES_IP_RASPBERRY:8088

Dostępne API obejmuje m.in.:
- GET /api/status
- GET /api/automation-status
- GET /api/automation-settings
- PUT /api/automation-settings
- GET /api/schedule
- PUT /api/schedule
- GET /api/schedule-status
- GET /api/manual
- POST /api/manual/activate
- POST /api/manual/deactivate/{output}
- POST /api/manual/clear
- GET /api/history
- GET /api/events
- GET /api/alerts
- GET /api/health

Panel WWW może zostać zrestartowany bez zatrzymywania głównego sterownika.

Portu 8088 nie należy przekierowywać na routerze. Panel jest przeznaczony do użytku w zaufanej sieci LAN.

## Historia SQLite

Historia jest domyślnie włączona:

    [history]
    enabled = true
    database_file = "runtime/history.db"
    sample_interval_seconds = 10.0

state.json zawiera bieżący stan, natomiast history.db przechowuje:
- pomiary w tabeli measurements,
- zdarzenia w tabeli events.

Rejestrowane są m.in.:
- niski poziom pelletu,
- powrót poziomu pelletu do normy,
- błędy sterownika,
- powrót sterownika do prawidłowej pracy,
- uruchomienie cyrkulacji CWU przez harmonogram,
- zakończenie uruchomienia cyrkulacji CWU przez harmonogram.

Szybkie sprawdzenie liczby rekordów:

    python - <<'PY'
    import sqlite3

    with sqlite3.connect("runtime/history.db") as db:
        print("Pomiary:", db.execute("SELECT COUNT(*) FROM measurements").fetchone()[0])
        print("Zdarzenia:", db.execute("SELECT COUNT(*) FROM events").fetchone()[0])
    PY

## Powiadomienia e-mail

Powiadomienia korzystają z SMTP STARTTLS.

Przykładowa konfiguracja:

    [email_notifications]
    enabled = true
    smtp_host = "smtp.gmail.com"
    smtp_port = 587
    use_starttls = true
    username_env = "KOTLOWNIA_SMTP_USERNAME"
    password_env = "KOTLOWNIA_SMTP_PASSWORD"
    sender = "kotlownia@example.com"
    recipients = ["adres@example.com"]

Hasła nie są przechowywane w repozytorium.

Dane logowania należy przechowywać w:

    config/kotlownia.env

Plik jest ignorowany przez Git. Wzór znajduje się w:

    config/kotlownia.env.example

Zmienne środowiskowe:
- KOTLOWNIA_SMTP_USERNAME
- KOTLOWNIA_SMTP_PASSWORD

## Architektura

Najważniejsze moduły:
- controller/main.py — punkt startowy CLI i obsługa sygnałów systemd,
- controller/application.py — główna pętla sterownika,
- controller/automation.py — deterministyczne reguły automatyki,
- controller/scheduler.py — harmonogram,
- controller/manual.py — sterowanie ręczne,
- controller/temperature.py — DS18B20,
- controller/pellet.py — HC-SR04 i filtr poziomu pelletu,
- controller/relays.py — sterowanie GPIO,
- controller/events.py — lokalna magistrala zdarzeń,
- controller/history.py — historia SQLite,
- controller/state.py — bieżący stan sterownika,
- api/app.py — API i panel WWW.

Główna zasada projektu: **panel WWW nie steruje sprzętem bezpośrednio**. Przekazuje jedynie żądania do głównego sterownika.

## Instalacja

Na Raspberry Pi:

    cd /home/eddy/Kotlownia2
    python3 -m venv .venv
    source .venv/bin/activate
    python -m pip install --upgrade pip
    python -m pip install -r requirements-dev.txt

Do uruchomienia bez narzędzi testowych:

    python -m pip install -r requirements.txt

Zależności sprzętowe obejmują m.in. gpiozero oraz backend lgpio.

## Testy

    cd /home/eddy/Kotlownia2
    .venv/bin/pytest

Pojedynczy cykl:

    .venv/bin/python -m controller.main --once

Sprawdzenie konfiguracji bez inicjalizacji GPIO:

    .venv/bin/python -m controller.main --check-config

## Tryb sprzętowy i symulacja

Główna konfiguracja:

    [application]
    simulation = false

Aktualnie projekt pracuje w trybie rzeczywistego GPIO.

Czujniki posiadają niezależne ustawienia simulation.

Przed zmianą okablowania lub podłączeniem obciążeń należy sprawdzić poziomy logiczne modułu przekaźników oraz zabezpieczenia elektryczne.

## Instalacja jako usługa systemd

Instalacja:

    cd /home/eddy/Kotlownia2
    ./scripts/install_service.sh

Uruchomienie:

    sudo systemctl start kotlownia.service

Status:

    systemctl status kotlownia.service

Logi:

    journalctl -u kotlownia.service -f

Restart:

    sudo systemctl restart kotlownia.service

Usługa głównego sterownika uruchamia się automatycznie po restarcie Raspberry Pi.

Panel WWW działa jako osobna usługa:

    sudo systemctl restart kotlownia-web.service
    systemctl status kotlownia-web.service

## Pliki runtime

Dane generowane podczas pracy nie powinny być przechowywane w Git:

    runtime/
    ├── state.json
    ├── history.db
    ├── schedule.json
    ├── manual_control.json
    └── automation_settings.json

## Bezpieczeństwo

- nie przechowuj haseł SMTP w repozytorium,
- nie przekierowuj panelu WWW do Internetu,
- przed pracą przy instalacji elektrycznej wyłącz zasilanie i sprawdź brak napięcia,
- sprawdź, czy przekaźniki i styczniki są przystosowane do rzeczywistego obciążenia,
- nie traktuj oprogramowania jako zamiennika fabrycznych zabezpieczeń kotła.

## Status projektu

Główne elementy sterowania, monitoringu, harmonogramów, ręcznego sterowania, historii, alarmów i panelu WWW są zaimplementowane.

Przed kolejnymi zmianami zalecane jest uruchomienie pełnego zestawu testów:

    .venv/bin/pytest
