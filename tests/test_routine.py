from datetime import datetime

from voxa.core.types import Intent
from voxa.services.simulated import SimulatedMusic
from voxa.services.weather import Weather
from voxa.skills.routine import RoutineSkill
from voxa.state.timers import TimerManager

MORNING = datetime(2026, 10, 24, 7, 15)


class FixedWeather:
    def __init__(self, weather):
        self.weather = weather

    async def today(self):
        return self.weather


async def test_good_morning_tells_time_weather_reminders_and_plays_music():
    timers = TimerManager(clock=lambda: MORNING.timestamp())
    timers.add_at(datetime(2026, 10, 24, 20, 0).timestamp(), "sacar la basura")
    timers.add_at(datetime(2026, 10, 25, 7, 0).timestamp(), None)  # mañana: no es de hoy
    timers.add(600, "el arroz")  # un temporizador no es un recordatorio
    music = SimulatedMusic()
    skill = RoutineSkill(timers, FixedWeather(Weather(13.6, 0, 24.2, 9.0, 40)), music, "mi playlist de la mañana", now=lambda: MORNING)
    said = await skill.handle(Intent("routine.good_morning"))
    assert said.speech == (
        "¡Buenos días! Son las 7 y cuarto de la mañana. Hay 14 grados; hoy, máxima de 24 y 40 % de probabilidad "
        "de lluvia. Hoy tienes: sacar la basura a las 8 de la noche."
    )
    assert music.calls == ["play:mi playlist de la mañana"]


async def test_good_night_mentions_what_comes_next():
    night = datetime(2026, 10, 24, 22, 30)
    timers = TimerManager(clock=lambda: night.timestamp())
    skill = RoutineSkill(timers, now=lambda: night)
    assert (await skill.handle(Intent("routine.good_night"))).speech == "Buenas noches."
    timers.add_at(datetime(2026, 10, 25, 6, 30).timestamp(), None)
    said = await skill.handle(Intent("routine.good_night"))
    assert said.speech == "Buenas noches. Te aviso: la alarma a las 6 y media de la mañana."
