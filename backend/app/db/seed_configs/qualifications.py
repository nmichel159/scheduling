"""Deterministic qualification draws for invented mock staff.

Mock people need qualifications before a workplace can be scheduled, and
drawing them at random is what keeps a demo roster from looking hand-placed.
A purely random draw is not safe on its own, though: it can leave a role with
too few holders to staff it every day, and a role nobody is left to cover
makes the month infeasible before the solver even starts. Every draw here is
therefore followed by a top-up, and every choice is seeded from the identity of
the person and the workplace rather than from the clock, so a database rebuilt
tomorrow holds the same roster as one rebuilt today.
"""

from app.db.seed_configs.availability import stable_random


def draw_qualifications(
    workplace: str,
    competence_names: list[str],
    emails: list[str],
    *,
    probability: float = 0.7,
    always: tuple[str, ...] = (),
) -> dict[str, list[str]]:
    """Give each person the `always` roles plus a random share of the rest.

    Args:
        workplace: Name the draw is seeded with, so two workplaces sharing a
            person still qualify them independently.
        competence_names: Every role the workplace offers, in display order.
        emails: People to qualify.
        probability: Chance that one optional role is drawn for one person.
        always: Roles everybody holds, whatever the draw says.

    Returns:
        One role list per person, never empty and in `competence_names` order.
    """
    qualifications: dict[str, list[str]] = {}
    for email in emails:
        generator = stable_random(workplace, "qualifications", email)
        chosen = [
            name
            for name in competence_names
            if name in always or generator.random() < probability
        ]
        if not chosen:
            chosen = [generator.choice(competence_names)]
        qualifications[email] = sorted(chosen, key=competence_names.index)
    return qualifications


def ensure_holders(
    workplace: str,
    qualifications: dict[str, list[str]],
    competence_names: list[str],
    minimum_holders: dict[str, int],
) -> dict[str, list[str]]:
    """Top up under-covered roles until each has enough qualified people.

    The minimum is a multiple of a role's daily demand rather than the demand
    itself, because a role also needs holders left over on the days its usual
    people are absent or resting after a duty.

    Returns:
        The same mapping, with roles added where they were short.
    """
    topped_up = {email: list(names) for email, names in qualifications.items()}
    for name, minimum in minimum_holders.items():
        holders = [email for email, names in topped_up.items() if name in names]
        candidates = [email for email in topped_up if name not in topped_up[email]]
        stable_random(workplace, "top-up", name).shuffle(candidates)
        while len(holders) < minimum and candidates:
            email = candidates.pop()
            topped_up[email].append(name)
            holders.append(email)
    return {
        email: sorted(names, key=competence_names.index)
        for email, names in topped_up.items()
    }
