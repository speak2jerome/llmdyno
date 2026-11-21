"""The service layer: everything the web API and the Python library do, as plain functions.

One module per area. Services return plain data and raise llmdyno.errors; the FastAPI routes in llmdyno/api
and the library in llmdyno/sdk are thin layers over them."""
