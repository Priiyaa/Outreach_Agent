from .ashby import Ashby
from .greenhouse import Greenhouse
from .lever import Lever
from .lists import Jobright, Simplify
from .workday import Workday

# Adding a source = one new file with a Source subclass, then list it here.
SOURCES = {cls.name: cls for cls in (Greenhouse, Lever, Ashby, Workday, Simplify, Jobright)}
