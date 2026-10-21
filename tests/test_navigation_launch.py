"""Check launch arguments consumed as Python expressions by Humble Nav2."""
import ast
from pathlib import Path


def test_localization_composition_argument_is_a_python_boolean():
    launch_file = (Path(__file__).resolve().parents[1] / "ros2_ws" / "src" /
                   "smart_car_decision" / "launch" / "navigation.launch.py")
    tree = ast.parse(launch_file.read_text(encoding="utf-8"))
    arguments = next(node for node in ast.walk(tree) if isinstance(node, ast.Dict)
                     and any(isinstance(key, ast.Constant) and key.value == "use_composition"
                             for key in node.keys))
    value = next(ast.literal_eval(value) for key, value in zip(arguments.keys, arguments.values)
                 if isinstance(key, ast.Constant) and key.value == "use_composition")
    # localization_launch.py uses PythonExpression(['not ', use_composition]).
    expression = ast.parse("not " + value, mode="eval")
    assert isinstance(expression.body, ast.UnaryOp)
    assert isinstance(expression.body.op, ast.Not)
    assert isinstance(expression.body.operand, ast.Constant)
    assert expression.body.operand.value is False
