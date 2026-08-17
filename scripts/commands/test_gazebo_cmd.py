import unittest

from scripts.commands.gazebo_cmd import gazebo_launch_script, gazebo_stop_script


class GazeboCommandTest(unittest.TestCase):
    def test_launch_script_uses_shared_novnc_display(self) -> None:
        script = gazebo_launch_script()

        self.assertIn('export DISPLAY="${DISPLAY:-novnc:0}"', script)
        self.assertIn("export QT_X11_NO_MITSHM=1", script)
        self.assertNotIn("Xvfb :99", script)

    def test_stop_script_targets_gz_processes_without_matching_parent_commands(self) -> None:
        script = gazebo_stop_script()

        self.assertIn("pgrep -f '[r]os2 launch turtlebot3_gazebo'", script)
        self.assertIn("ps -eo pid=,args=", script)
        self.assertIn("/[g]z sim/", script)
        self.assertIn('kill "$pid"', script)
        self.assertNotIn("pkill -f", script)


if __name__ == "__main__":
    unittest.main()
