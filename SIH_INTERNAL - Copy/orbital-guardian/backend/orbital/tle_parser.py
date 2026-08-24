from sgp4.api import Satrec


def parse_tle(name, line1, line2):
    """
    Convert two TLE lines into an SGP4 satellite object.
    """

    satellite = Satrec.twoline2rv(line1, line2)

    return {"name": name, "satellite": satellite, "line1": line1, "line2": line2}


def load_tle_file(filepath):
    """
    Read multiple 3-line TLE records from a file.

    Expected format:

    Satellite Name
    TLE Line 1
    TLE Line 2

    Satellite Name
    TLE Line 1
    TLE Line 2
    """

    satellites = []

    with open(filepath, "r") as file:
        lines = [line.strip() for line in file if line.strip()]

    if len(lines) % 3 != 0:
        raise ValueError(
            "TLE file must contain groups of 3 lines: name, line 1, line 2."
        )

    for i in range(0, len(lines), 3):
        name = lines[i]
        line1 = lines[i + 1]
        line2 = lines[i + 2]

        satellite = parse_tle(name, line1, line2)

        satellites.append(satellite)

    return satellites
