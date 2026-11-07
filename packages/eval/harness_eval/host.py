"""What the eval package adds to the core (package.toml [provides] host;
harness/extensions.py): harness run EXPERIMENT and harness doctor EXPERIMENT, the core
hands them over; an experiment loaded for a conversation on a bench's worker (the session
host's POST /api/conversations) and installed first (preflight); a bench's hooks (load_bench)."""


def run_experiment(argv) -> int:
    from harness_eval import commands

    return commands.run_experiment(argv)


def doctor_experiment(argv) -> int:
    from harness_eval import commands

    return commands.doctor_experiment(argv)


def load_experiment(*args, **options):
    from harness_eval import experiments

    return experiments.load_experiment(*args, frozen_identity=False, **options)


def preflight(run, log=print):
    from harness_eval import suite

    return suite.preflight(run, log=log)


def load_bench(name):
    """A bench with its hooks (the core's harness install prepares a checkout with them)."""
    from harness_eval import bench

    return bench.load_bench(name)
