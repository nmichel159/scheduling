# Antigravity Rule: Backend Pydantic Schemas

When creating or modifying data validation and serialization models in `backend/schemas/`, you must strictly adhere to these rules:

## 1. Separation and Naming Strategy
* Keep schema definitions mapped 1:1 to their database domains (e.g., schemas for `models/shift.py` live strictly in `schemas/shift.py`).
* For every domain, you must implement at least 4 distinct Pydantic classes to handle different states of data lifecycles:
  1. `BaseModel` (e.g., `ShiftBase`): Contains fields shared by both reading and writing operations.
  2. `CreateSchema` (e.g., `ShiftCreate`): Used for input data on creation. Contains fields required to build the object.
  3. `UpdateSchema` (e.g., `ShiftUpdate`): Used for updating data. **All fields must be optional (`Optional[...] = None`)** to support partial updates (PATCH behavior).
  4. `ResponseSchema` (e.g., `ShiftResponse`): Used for data serialization returned to the frontend. Must include the `id` field.

## 2. Configuration & Validation
* Every `ResponseSchema` must explicitly include the configuration class to enable ORM compatibility:
  ```python
  class Config:
      from_attributes = True