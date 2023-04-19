from pathlib import Path

path_types = {
    'is_dir': 'directory',
    'is_file': 'file',
    'is_mount': 'mount point',
    'is_symlink': 'symlink',
    'is_block_device': 'block device',
    'is_char_device': 'char device',
    'is_fifo': 'FIFO',
    'is_socket': 'socket',
}


def path_type(p: Path) -> str:
    """
    Find out what sort of thing a path is.
    """
    assert p.exists(), 'path does not exist'
    for method, name in path_types.items():
        if getattr(p, method)():
            return name

    return 'unknown'
