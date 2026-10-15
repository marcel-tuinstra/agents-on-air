"""Reject pushes whose source is not the clean HEAD that verification tests."""
import subprocess
import sys

from verify import ROOT, verify

ZERO = '0' * 40


def git(*args):
    return subprocess.run(['git', *args], cwd=ROOT, capture_output=True,
                          text=True, check=True).stdout.strip()


def check_push(lines):
    head = git('rev-parse', 'HEAD')
    updates = []
    for line in lines:
        fields = line.split()
        if len(fields) != 4:
            raise ValueError('Unexpected Git pre-push input.')
        local_ref, local_sha, remote_ref, remote_sha = fields
        if local_sha == ZERO:
            continue  # Deleting a remote ref pushes no new code.
        peeled = git('rev-parse', local_ref + '^{}')
        if peeled != head:
            raise ValueError(f'{local_ref} points to {peeled[:12]}, not HEAD {head[:12]}; '
                             'check out and verify the exact commit you intend to push.')
        submitted = git('rev-parse', local_sha + '^{}')
        if submitted != head:
            raise ValueError(f'{local_ref} was queued at {submitted[:12]}, but HEAD is now '
                             f'{head[:12]}; retry the push from a stable checkout.')
        updates.append((local_ref, remote_ref))
    if not updates:
        return False
    if git('status', '--porcelain', '--untracked-files=all'):
        raise ValueError('The working tree or index differs from HEAD. Commit or remove those '
                         'changes before pushing so verification tests the pushed tree.')
    return True


if __name__ == '__main__':
    try:
        updates = tuple(sys.stdin)
        if check_push(updates):
            verify()
            # Catch tests or another process changing the checkout during verification.
            check_push(updates)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f'pre-push: {error}', file=sys.stderr)
        sys.exit(1)
