@echo off
echo ===================================================
echo Quick Git Push Script (QA)
echo ===================================================

:: Check for changes
git status -s
echo.

:: Prompt for a commit message
set /p commit_msg="Enter commit message (or press enter for 'QA Updates'): "

:: Set default message if empty
if "%commit_msg%"=="" set commit_msg=QA Updates

:: Add, Commit, Push
echo.
echo Adding files...
git add .

echo.
echo Committing with message: "%commit_msg%"...
git commit -m "%commit_msg%"

echo.
echo Pushing to repository...
git push

echo.
echo Done!
pause
