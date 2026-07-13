import sys
import os

# Go up 3 levels to reach the project root directory so Python can find the 'core' folder
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)

from PyQt5.QtWidgets import QApplication
from core.transparent_overlay import draw_hologram_target

def run_visual_test():
    app = QApplication(sys.argv)
    
    print("Deploying Hologram Target...")
    
    draw_hologram_target(
        x=400, 
        y=300, 
        width=600, 
        height=400, 
        label="JARVIS TARGET ACQUIRED", 
        color="#00ff88"
    )
    
    print("Hologram deployed! You should see a green glowing box.")
    print("It will automatically fade out after 2 seconds.")
    
    sys.exit(app.exec_())

if __name__ == "__main__":
    run_visual_test()