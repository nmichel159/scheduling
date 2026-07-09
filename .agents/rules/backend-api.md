# Antigravity Rule: Backend FastAPI Routers & Endpoints

When creating or modifying API endpoints in `backend/api/`, you must strictly adhere to these rules:

## 1. RESTful Path Design
Every domain must expose a standard REST routing architecture implementing all 4 HTTP verbs. Paths must be pluralized:
* `POST /domain/` - Create a resource (Returns `211 Created`).
* `GET /domain/` - List resources (Must support pagination parameters `skip` and `limit`).
* `GET /domain/{id}` - Retrieve a single resource by ID (Returns `404` if not found).
* `PUT /domain/{id}` - Update a resource (Must handle partial updates gracefully using `exclude_unset=True`).
* `DELETE /domain/{id}` - Remove a resource (Returns `204 No Content`).

## 2. Dependency Injection & Transactions
* Database sessions must be safely injected into endpoints via FastAPI `Depends()`, utilizing a unified dependency function (e.g., `get_db`).
* The API router layer should only handle HTTP status codes, request parsing, and response serialization. Complex domain validations or cross-table operations must be delegated to the `services/` layer.

## 3. Strict Return Typing
* Every single endpoint function must explicitly declare its `response_model` property in the decorator (e.g., `@router.get("/", response_model=List[EmployeeResponse])`). Never return raw dictionaries or un-validated JSON.