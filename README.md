# Kotłownia 2.0

Nowa wersja sterownika kotłowni działającego na Raspberry Pi.

## Założenia

- sterownik działa autonomicznie bez Internetu,
- urządzenia są sterowane przez przekaźniki aktywne stanem LOW,
- panel WWW i aplikacja Android korzystają ze wspólnego API,
- konfiguracja automatyki nie jest zaszyta bezpośrednio w kodzie,
- aplikacja jest uruchamiana i nadzorowana przez systemd,
- awaria panelu WWW lub Internetu nie może zatrzymać sterowania.

## Struktura

- controller/ – główna logika sterownika
- api/ – REST API
- web/ – panel WWW
- android/ – aplikacja Android
- config/ – konfiguracja
- systemd/ – jednostki systemd
- tests/ – testy
- docs/ – dokumentacja
- legacy/ – wybrane fragmenty starej wersji

## Status

Projekt jest obecnie przygotowywany.

Aktualnie działająca wersja nadal znajduje się w:

/home/eddy/kotlownia
