import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import boundary_core as bc

def load(name):
    with open(os.path.join(os.path.dirname(__file__), name), encoding="utf-8") as f:
        return bc.analyze(f.read())

class CoreTest(unittest.TestCase):
    def test_lab_program(self):
        r = load("analyzed.rb")
        self.assertEqual(r.v, 38)
        self.assertEqual(r.sa, 70)
        self.assertAlmostEqual(r.so, 1 - 37 / 70)
        self.assertEqual(list(r.selection), [5, 9, 14, 15, 17, 25, 27, 30, 32, 34])
        self.assertEqual({v: s.complexity for v, s in r.selection.items()},
                         {5: 4, 9: 3, 14: 8, 15: 5, 17: 3, 25: 3, 27: 2, 30: 7, 32: 5, 34: 3})

    def test_methodical_example_fig1(self):
        r = load("fig1_case.rb")
        self.assertEqual((r.v, r.sa), (7, 10))
        self.assertAlmostEqual(r.so, 0.4)

    def test_straight_line(self):
        r = bc.analyze("a = 1\nb = 2\n")
        self.assertEqual((r.v, r.sa), (4, 3))

if __name__ == "__main__":
    unittest.main()
