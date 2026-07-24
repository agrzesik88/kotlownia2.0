from controller.events import ControllerEvent, EventBus, EventType


def test_event_bus_delivers_event_to_subscriber() -> None:
    received: list[ControllerEvent] = []
    bus = EventBus()
    bus.subscribe(received.append)

    event = ControllerEvent(EventType.PELLET_LOW, "niski pellet")
    bus.publish(event)

    assert received == [event]


def test_event_bus_does_not_register_same_handler_twice() -> None:
    received: list[ControllerEvent] = []
    bus = EventBus()
    bus.subscribe(received.append)
    bus.subscribe(received.append)

    bus.publish(ControllerEvent(EventType.CONTROLLER_RECOVERED, "ok"))

    assert len(received) == 1
