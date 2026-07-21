# Sprzęt i mapowanie GPIO

## Przekaźniki

Moduł przekaźników jest aktywny stanem LOW:

- `GPIO LOW` – przekaźnik włączony,
- `GPIO HIGH` – przekaźnik wyłączony.

| GPIO | Urządzenie |
|---:|---|
| 6 | Pompa cyrkulacyjna CWU |
| 13 | Pompa ładująca bojler |
| 19 | Zasilanie grzałki elektrycznej bojlera |
| 26 | Stałe zasilanie pieca na pellet |

## Temperatura

Czujnik DS18B20 mierzy temperaturę na zewnętrznej powierzchni rury wychodzącej z pieca na pellet.

Instalacja jest starszym układem otwartym z obiegiem grawitacyjnym.

## Poziom pelletu

Czujnik ultradźwiękowy HC-SR04:

| Funkcja | GPIO |
|---|---:|
| TRIG | 23 |
| ECHO | 24 |

## Ważne

Raspberry Pi steruje wyłącznie wejściami modułu przekaźnikowego. Obwody sieciowe urządzeń są przełączane przez styki przekaźników.
