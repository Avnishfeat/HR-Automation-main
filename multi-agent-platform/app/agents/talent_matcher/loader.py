import json

def load_employees(filepath: str):
    employees = []
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            employees.append(json.loads(line))
    return employees
