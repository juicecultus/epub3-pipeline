class Qt: pass
def __getattr__(name): return type(name,(),{})
