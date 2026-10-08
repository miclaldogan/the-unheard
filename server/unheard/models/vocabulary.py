"""Controlled initial source-label vocabulary for zero-shot matching (environmental sounds).

Display names and prompts are separate from the normalised slug stored in ``label.slug``.
Users extend this list from the Teach panel; their labels get a text prior from their name.
"""

from __future__ import annotations

PROMPT_TEMPLATE = "The sound of {}."

# (slug, display name, prompt noun phrase)
VOCABULARY: list[tuple[str, str, str]] = [
    ("rain", "Rain", "rain falling"),
    ("running_water", "Running water", "a stream of running water"),
    ("sea_waves", "Sea waves", "sea waves on a shore"),
    ("fountain", "Fountain", "a water fountain"),
    ("wind", "Wind", "wind blowing"),
    ("rustling_leaves", "Rustling leaves", "leaves rustling in the wind"),
    ("thunder", "Thunder", "thunder"),
    ("birds", "Birds", "birds chirping"),
    ("crow", "Crow", "a crow cawing"),
    ("dog", "Dog", "a dog barking"),
    ("cat", "Cat", "a cat meowing"),
    ("insects", "Insects", "crickets and insects"),
    ("footsteps", "Footsteps", "footsteps walking"),
    ("speech", "Human speech", "people talking"),
    ("children", "Children playing", "children playing"),
    ("laughter", "Laughter", "people laughing"),
    ("car_engine", "Car engine", "a car engine running"),
    ("traffic", "Traffic", "road traffic"),
    ("car_horn", "Car horn", "a car horn"),
    ("motorcycle", "Motorcycle", "a motorcycle engine"),
    ("airplane", "Airplane", "an airplane flying overhead"),
    ("train", "Train", "a train passing"),
    ("siren", "Siren", "an emergency siren"),
    ("bicycle", "Bicycle", "a bicycle"),
    ("church_bells", "Church bells", "church bells ringing"),
    ("construction", "Construction", "a construction site"),
    ("drilling", "Drilling", "a power drill"),
    ("hammering", "Hammering", "hammering"),
    ("lawn_mower", "Lawn mower", "a lawn mower"),
    ("chainsaw", "Chainsaw", "a chainsaw"),
    ("door", "Door", "a door opening and closing"),
    ("typing", "Keyboard typing", "typing on a keyboard"),
    ("music", "Music", "music playing"),
    ("fire", "Fire crackling", "a fire crackling"),
    ("helicopter", "Helicopter", "a helicopter"),
    ("ventilation_hum", "Ventilation hum", "an air conditioner or ventilation hum"),
    ("wind_chimes", "Wind chimes", "wind chimes"),
    ("clock", "Clock ticking", "a clock ticking"),
    ("silence", "Room tone", "a quiet room with background noise"),
]


def prompt_for(name_or_phrase: str) -> str:
    return PROMPT_TEMPLATE.format(name_or_phrase.strip().rstrip("."))
