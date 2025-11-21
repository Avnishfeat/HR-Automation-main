@ECHO OFF
TITLE Running Project Tests...
ECHO =======================================
ECHO  RUNNING TEST SUITE ^& COVERAGE
ECHO =======================================
ECHO.

:: Clean up ALL coverage-related files
ECHO Cleaning old coverage data...
IF EXIST .coverage DEL /F /Q .coverage 2>NUL
IF EXIST htmlcov RMDIR /S /Q htmlcov 2>NUL
FOR /F "tokens=*" %%G IN ('DIR /B .coverage.* 2^>NUL') DO DEL /F /Q "%%G"
coverage erase 2>NUL
ECHO.

ECHO Running pytest...
pytest --cov=app --cov-report=term-missing --cov-report=html --no-cov-on-fail

:: Check if pytest ran successfully
IF %ERRORLEVEL% NEQ 0 (
    ECHO.
    ECHO ==========================
    ECHO  TESTS FAILED!
    ECHO ==========================
    GOTO End
)

ECHO.
ECHO =======================================
ECHO  TESTS PASSED SUCCESSFULLY!
ECHO =======================================
ECHO.
ECHO An HTML coverage report has been generated in the 'htmlcov' directory.
ECHO Opening report...

:: Open the generated HTML report
START "" .\htmlcov\index.html

:End
ECHO.
ECHO Press any key to exit...
PAUSE > NUL