"""Reset the simulator to the dock with a fresh mapd (simreset.reset), as duck-eval does before each goal."""
from duck_lab.nav import simreset

simreset.reset("apartment_backlash")
print("RESET OK")
