import os
import zipfile
import sys
from pathlib import Path

def create_clean_archive():
    root_dir = Path(__file__).resolve().parent.parent
    desktop_dir = root_dir.parent
    output_zip = desktop_dir / "scholarship_star.zip"
    
    EXCLUDE_DIR_NAMES = {
        '.git', '.venv', 'venv', '__pycache__', 
        '.pytest_cache', '.ruff_cache', '.mypy_cache', '.cache',
        '.idea', '.vscode'
    }
    EXCLUDE_FILE_NAMES = {
        '.env', 'service_account.json', 'scholarship_star.zip', 'scholarship_project.zip',
        '.DS_Store', 'Thumbs.db'
    }
    EXCLUDE_EXTENSIONS = {'.pyc', '.pyo', '.tmp', '.log'}

    file_count = 0
    total_uncompressed_bytes = 0

    print(f"Compressing from: {root_dir}")
    print(f"Target archive: {output_zip}")

    with zipfile.ZipFile(output_zip, 'w', compression=zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(root_dir):
            # Prune unwanted directories
            dirs[:] = [d for d in dirs if d not in EXCLUDE_DIR_NAMES and not d.startswith('.')]
            
            for file in files:
                if file in EXCLUDE_FILE_NAMES:
                    continue
                ext = Path(file).suffix.lower()
                if ext in EXCLUDE_EXTENSIONS:
                    continue
                
                full_path = Path(root) / file
                rel_path = full_path.relative_to(root_dir)
                archive_name = Path("scholarship-star") / rel_path

                zf.write(full_path, str(archive_name))
                file_count += 1
                total_uncompressed_bytes += full_path.stat().st_size

    zip_size_bytes = output_zip.stat().st_size
    print("\nSUCCESS!")
    print(f"Total files packaged: {file_count}")
    print(f"Uncompressed size:    {total_uncompressed_bytes / (1024*1024):.2f} MB")
    print(f"Clean Zip size:       {zip_size_bytes / (1024*1024):.2f} MB ({zip_size_bytes} bytes)")
    print(f"Archive file:         {output_zip}")

if __name__ == "__main__":
    create_clean_archive()
