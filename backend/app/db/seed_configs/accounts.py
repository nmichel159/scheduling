"""The sign-in accounts the demo profile keeps alive, and what each one is for.

A reset deletes every user row, and an account missing from the profile comes
back on the next login with the EMPLOYEE role and nothing else. Every account
somebody actually signs in with therefore belongs here, with the roles it needs.

Permissions are decided by role level, and a level reaches everything the
levels below it reach:

* ``EMPLOYEE`` (1) works a rota and submits its own absences and day requests.
* ``LEADER`` (2) builds and approves schedules -- but only for the workplaces
  that name it as their manager, which is the link that makes an account the
  scheduler of one clinic rather than of all of them.
* ``AMBULANCE_OVERSEER`` (3) reaches every workplace instead of only the ones
  it manages.
* ``ANALYST`` (4) reads the hospital-wide reports.
"""

#: Builds the schedules for I.KAIM; the clinic names this account as manager.
IKAIM_SCHEDULER_EMAIL = "3x3mail159@gmail.com"
#: Oversees the clinics and works the I.KAIM rota, but schedules nothing itself.
OVERSEER_EMAIL = "noro.michel159@gmail.com"
#: Reads the hospital-wide reports and nothing else.
ANALYST_EMAIL = "norko.michel@gmail.com"
#: A plain employee of I.KAIM, on no other roster.
IKAIM_EMPLOYEE_EMAIL = "zamestnanecunlp@gmail.com"
#: Kept so that a reset does not delete it; no workplace of its own yet.
GUEST_EMAIL = "office@3x3sport.com"

#: Schedulers of the three departments around I.KAIM.
SECOND_KAIM_MANAGER_EMAIL = "a14325999@gmail.com"
KDAIM_MANAGER_EMAIL = "alexthesecond0000@gmail.com"
URGENT_MANAGER_EMAIL = "gsemanisin@gmail.com"

USERS = [
    {"email": IKAIM_SCHEDULER_EMAIL, "full_name": "Norbert Michel"},
    {"email": OVERSEER_EMAIL, "full_name": "Noro Micheľ"},
    {"email": ANALYST_EMAIL, "full_name": "Noro Micheľ"},
    {"email": IKAIM_EMPLOYEE_EMAIL, "full_name": "Zamestnanec UNLP"},
    {"email": GUEST_EMAIL, "full_name": "Jozef Halás"},
    {"email": SECOND_KAIM_MANAGER_EMAIL, "full_name": "Leader A"},
    {"email": KDAIM_MANAGER_EMAIL, "full_name": "Alex the Second"},
    {"email": URGENT_MANAGER_EMAIL, "full_name": "Gabriel Semanisin"},
]

ROLE_ASSIGNMENTS = {
    IKAIM_SCHEDULER_EMAIL: ["LEADER"],
    OVERSEER_EMAIL: ["EMPLOYEE", "AMBULANCE_OVERSEER"],
    ANALYST_EMAIL: ["ANALYST"],
    IKAIM_EMPLOYEE_EMAIL: ["EMPLOYEE"],
    GUEST_EMAIL: ["EMPLOYEE"],
    SECOND_KAIM_MANAGER_EMAIL: ["EMPLOYEE", "LEADER"],
    KDAIM_MANAGER_EMAIL: ["EMPLOYEE", "LEADER"],
    URGENT_MANAGER_EMAIL: ["EMPLOYEE", "LEADER", "ANALYST"],
}
