"""Create nine repeatable Lorem-ipsum recipes for PDF layout checks."""

from sqlalchemy import select

from .database import RecipeRecord, SessionLocal, init_db


LENGTHS = ("kurz", "mittel", "lang")
DESCRIPTION_SENTENCES = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
    "Praesent commodo, nibh at cursus tempor, ligula neque luctus sapien, vitae pretium justo sem sed urna.",
    "Donec aliquet magna in augue posuere, non finibus mauris facilisis.",
    "Vivamus pharetra sapien at nisl dictum, sed fermentum sem malesuada.",
)
STEP_SENTENCES = (
    "Lorem ipsum dolor sit amet, consectetur adipiscing elit.",
    "Praesent commodo ligula neque, ut fermentum mauris facilisis vitae.",
    "Donec aliquet magna in augue posuere, sed tempus justo volutpat.",
)


def make_recipe(description_length: int, ingredient_length: int, step_length: int, number: int) -> RecipeRecord:
    title = (f"PDF-Test {number:02d} – Beschreibung {LENGTHS[description_length]}, "
             f"Zutaten {LENGTHS[ingredient_length]}, Zubereitung {LENGTHS[step_length]}")
    description_count = (1, 4, 10)[description_length]
    ingredient_count = (3, 12, 24)[ingredient_length]
    step_count = (2, 6, 12)[step_length]
    step_sentences = (1, 2, 3)[step_length]
    return RecipeRecord(
        title=title,
        description=" ".join(DESCRIPTION_SENTENCES[i % len(DESCRIPTION_SENTENCES)]
                             for i in range(description_count)),
        source_type="test",
        source_name="Lorem ipsum / PDF-Test",
        servings="2",
        categories=["PDF-Test"],
        tags=[LENGTHS[description_length], LENGTHS[ingredient_length], LENGTHS[step_length]],
        ingredients=[
            {"text": f"{i * 25} g Lorem-Zutat {i:02d} – dolor sit amet, consectetur adipiscing elit."}
            for i in range(1, ingredient_count + 1)
        ],
        steps=[
            {"text": " ".join(STEP_SENTENCES[(i + j) % len(STEP_SENTENCES)]
                               for j in range(step_sentences))}
            for i in range(step_count)
        ],
    )


def main() -> None:
    init_db()
    with SessionLocal() as db:
        for description_length in range(3):
            for ingredient_length in range(3):
                step_length = (description_length + ingredient_length) % 3
                number = description_length * 3 + ingredient_length + 1
                recipe = make_recipe(description_length, ingredient_length, step_length, number)
                existing = db.scalar(select(RecipeRecord).where(RecipeRecord.title == recipe.title))
                if existing is None:
                    db.add(recipe)
                    db.flush()
                    print(f"Neu: #{recipe.id} {recipe.title}")
                else:
                    print(f"Vorhanden: #{existing.id} {existing.title}")
        db.commit()


if __name__ == "__main__":
    main()
