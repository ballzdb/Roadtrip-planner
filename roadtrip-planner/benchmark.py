"""
Benchmark script — not part of the main app, just a tool to measure and
compare the three TSP algorithms at increasing numbers of cities.

Run it directly:
    python benchmark.py

This generates random coordinates within the continental US and times
each algorithm. Brute force is skipped past 9 cities and Held-Karp is
skipped past 13 cities, since both become impractically slow and this
script would otherwise hang for a very long time.
"""

import time
import random
from main import brute_force_tsp, held_karp_tsp, nearest_neighbor_tsp


def random_coords(n, seed=42):
    random.seed(seed)
    # rough bounding box for the continental US, in [lon, lat] to match ORS format
    return [[random.uniform(-124, -70), random.uniform(25, 49)] for _ in range(n)]


def time_it(func, coords):
    start = time.perf_counter()
    order, dist = func(coords)
    elapsed_ms = (time.perf_counter() - start) * 1000
    return elapsed_ms, dist


def main():
    print(f"{'Cities':<8}{'Brute Force':<18}{'Held-Karp':<18}{'Nearest Neighbor':<18}")
    print("-" * 62)

    for n in [4, 6, 8, 9, 10, 12, 13, 15]:
        coords = random_coords(n)
        row = [str(n)]

        if n <= 9:
            t, _ = time_it(brute_force_tsp, coords)
            row.append(f"{t:.2f} ms")
        else:
            row.append("skipped")

        if n <= 13:
            t, _ = time_it(held_karp_tsp, coords)
            row.append(f"{t:.2f} ms")
        else:
            row.append("skipped")

        t, _ = time_it(nearest_neighbor_tsp, coords)
        row.append(f"{t:.2f} ms")

        print(f"{row[0]:<8}{row[1]:<18}{row[2]:<18}{row[3]:<18}")


if __name__ == "__main__":
    main()
