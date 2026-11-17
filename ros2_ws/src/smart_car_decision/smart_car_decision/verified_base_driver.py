"""Entry point for the independently staged, hash-checked vendor overlay."""
def main():
    from .serial_binding import load_profile
    load_profile()  # No legacy fallback, even when old launch configuration survives.
    try:
        from .guarded_vendor_driver import main as vendor_main
    except ImportError as exc:
        raise RuntimeError('verified vendor overlay not prepared; refuse legacy SDK fallback') from exc
    return vendor_main()
