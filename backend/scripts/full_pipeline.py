import argparse
import subprocess
import os
import sys
import time

def run_step(script_name, args=[]):
    script_path = os.path.join(os.path.dirname(__file__), script_name)
    if not os.path.exists(script_path):
        print(f"❌ Script not found: {script_name}")
        return False
    
    print(f"\n🚀 Running {script_name}...")
    start_time = time.time()
    
    cmd = [sys.executable, script_path] + args
    try:
        # Stream output to console
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in process.stdout:
            print(line, end='')
        
        process.wait()
        if process.returncode != 0:
            print(f"❌ {script_name} failed with code {process.returncode}")
            return False
            
    except Exception as e:
        print(f"❌ Execution error: {e}")
        return False

    elapsed = time.time() - start_time
    print(f"✅ {script_name} completed in {elapsed:.1f}s")
    return True

def main():
    parser = argparse.ArgumentParser(description="PastLead Full Import Pipeline")
    parser.add_argument("mbox_path", help="Path to the .mbox file")
    parser.add_argument("--skip-import", action="store_true", help="Skip mbox import, just reconstruct and embed")
    args = parser.parse_args()

    if not os.path.exists(args.mbox_path) and not args.skip_import:
        print(f"❌ Error: File not found: {args.mbox_path}")
        sys.exit(1)

    print("==========================================")
    print("   PastLead: Full Data Pipeline Setup    ")
    print("==========================================")
    
    # 1. Import Mbox (Robust Version)
    # This now handles Subjects, Bodies, and Headers correctly in one pass using mailbox module.
    if not args.skip_import:
        if not run_step("import_mbox.py", [args.mbox_path]):
            sys.exit(1)
    
    # 2. Extract Bodies -> REMOVED
    # The new import_mbox.py does this automatically.

    # 3. Reconstruct Threads (Strict Version is usually best)
    if not run_step("reconstruct_threads_strict.py"):
        sys.exit(1)

    # 3.2 Filtering (Remove garbage/machine emails)
    # Must run BEFORE scoring to avoid processing junk
    if not run_step("run_filtering.py"):
        sys.exit(1)

    # 3.5 Extract Features & Scores
    if not run_step("extract_features.py"):
        sys.exit(1)

    # 4. Generate Embeddings (Vector search prep)
    # Skipped for SQLite migration (no pgvector support)
    # if not run_step("generate_embeddings.py"):
    #     sys.exit(1)

    print("\n🎉 All steps completed successfully!")
    print("You can now start the server: uvicorn app.main:app --reload")

if __name__ == "__main__":
    main()
