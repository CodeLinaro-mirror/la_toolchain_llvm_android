import atexit
import json
import os

class ToolchainBuild:
    BuildTime = []

    @classmethod
    def report(cls):
        num_cores = os.cpu_count()
        # The build time is measured in seconds.
        result = {"Cores": num_cores, "BuildTime": cls.BuildTime}
        return json.dumps(result)

    @classmethod
    def report_to_file(cls, outfile):
        with open(outfile, 'w') as out:
            out.write(cls.report())

    @classmethod
    def register_atexit(cls, outfile):
        """Register report_to_file(outfile) to run at exit."""
        atexit.register(cls.report_to_file, outfile)