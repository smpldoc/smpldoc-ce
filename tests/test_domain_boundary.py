"""domain/ imports nothing from a cloud library or an adapter: only the standard library."""
import ast
import sys
import unittest
from pathlib import Path

DOMAIN = Path(__file__).resolve().parent.parent / "smpldoc" / "domain"


class DomainBoundary(unittest.TestCase):
    def test_domain_imports_only_stdlib_and_itself(self):
        files = list(DOMAIN.glob("*.py"))
        self.assertTrue(files)
        for path in files:
            for node in ast.walk(ast.parse(path.read_text())):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom):
                    if node.level:  # relative import inside domain/
                        continue
                    names = [node.module or ""]
                for name in names:
                    top = name.split(".")[0]
                    ok = top in sys.stdlib_module_names or name.startswith("smpldoc.domain") or name == "smpldoc"
                    self.assertTrue(ok, f"{path.name} imports {name}")
                    self.assertFalse(name.startswith("smpldoc.adapters"), f"{path.name} imports an adapter")


if __name__ == "__main__":
    unittest.main()
