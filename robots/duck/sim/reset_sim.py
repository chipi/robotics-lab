"""Reset the simulator to the dock with a fresh mapd (the host's reset, simhost.reset), as duck-eval does before each goal."""
import simhost

simhost.reset(simhost.load(), "apartment_backlash")
print("RESET OK")
