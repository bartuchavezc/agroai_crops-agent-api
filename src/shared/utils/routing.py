def route_with_and_without_slash(method, path: str, **kwargs):
    """Register a route for `path` and `path + '/'` (clients differ on trailing slashes)."""
    def decorator(func):
        method(path, **kwargs)(func)
        method(path + "/", include_in_schema=False, **kwargs)(func)
        return func
    return decorator
