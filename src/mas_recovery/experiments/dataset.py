"""Seeded synthetic tasks with feasible, budget-limited, and stock-limited cases."""

import random

from mas_recovery.core.schemas import Product, Task


def generate_tasks(count: int = 6, seed: int = 291) -> list[Task]:
    if count < 1:
        raise ValueError("count must be positive")
    rng = random.Random(seed)
    tasks = []
    for i in range(count):
        quantity, price = rng.randint(2, 5), rng.randint(20, 80)
        stock = quantity - 1 if i % 3 == 2 else quantity + 2
        budget = quantity * price - 1 if i % 3 == 1 else quantity * (price + 10)
        catalog = tuple(
            Product(
                id=f"item-{j}",
                supplier="approved" if j < 2 else "unapproved",
                unit_price=price + j * 10 if j < 2 else max(1, price - 10),
                stock=stock,
                version=2,
                previous_price=max(1, price - 10),
                previous_stock=quantity + 3,
                previous_version=1,
            )
            for j in range(3)
        )
        tasks.append(
            Task(
                id=f"purchase-{seed}-{i:03}",
                quantity=quantity,
                unit_price=price,
                budget=budget,
                catalog=catalog,
            )
        )
    return tasks
