# Commands to Fix Xcode Beta Issue (run these yourself in terminal)

## Check current Xcode selection:
xcode-select --print-path

## Switch to a stable Xcode (if you install one):
sudo xcode-select -s /Applications/Xcode.app/Contents/Developer

## If you have a different Xcode path:
sudo xcode-select -s /Applications/Xcode-15.4.app/Contents/Developer

## Verify it worked:
xcodebuild -version

## If you need to reset to default:
sudo xcode-select --reset