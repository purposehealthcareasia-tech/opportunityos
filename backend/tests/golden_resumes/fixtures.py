"""Golden résumé fixtures — 10 synthetic, clearly-labeled test résumés.

Every résumé in this file is FICTIONAL. Emails end with @example.com, phones are +1-555-01xx.
The names include the token "TESTUSER" so no reasonable person mistakes them for real candidates.
"""
from __future__ import annotations

FIXTURES: list[dict] = [
    {
        "slug": "resume_01",
        "text": """Aditi Rao TESTUSER
aditi.rao.testuser@example.com | +1-555-0100 | Boston, MA
linkedin.com/in/aditi-rao-testuser

EDUCATION
Massachusetts Institute of Technology
MS in Mechanical Engineering, 2022 - 2024, GPA 3.8

IIT Bombay
BTech in Mechanical Engineering, 2016 - 2020, GPA 3.6

EMPLOYMENT
Rivian - Battery Systems Engineer, 2024-06 to Present
- Redesigned cell-level busbar geometry, reducing joint resistance 18%.

Zoox - Battery Test Intern, 2023-05 to 2023-08
- Built DAQ instrumentation for cell-level aging benches.

SKILLS
MATLAB, Simulink, Python, Ansys, GD&T, LabVIEW
""",
        "expected": {
            "name": "Aditi Rao",
            "emails": ["aditi.rao.testuser@example.com"],
            "phones": ["555-0100"],
            "locations": [{"city": "Boston", "state": "MA"}],
            "links": [{"kind": "linkedin", "substring": "aditi-rao-testuser"}],
            "education": [
                {"institution": "MIT", "degree": "MS"},
                {"institution": "IIT Bombay", "degree": "BTech"},
            ],
            "employment": [
                {"company": "Rivian", "role": "Battery Systems Engineer"},
                {"company": "Zoox", "role": "Battery Test"},
            ],
            "skills": ["MATLAB", "Simulink", "Python"],
        },
    },
    {
        "slug": "resume_02",
        "text": """Rohan Mehta TESTUSER
rohan.mehta.testuser@example.com | +1-555-0101 | Detroit, MI

EDUCATION
University of Michigan
MS in Automotive Engineering, 2020 - 2022

Purdue University
BS in Mechanical Engineering, 2016 - 2020

EMPLOYMENT
Ford Motor Company - HIL Simulation Engineer, 2022-07 to Present
- Owned HIL bench for a chassis controls project.

SKILLS
MATLAB, Simulink, HIL, dSPACE, CAN, Vector CANoe
""",
        "expected": {
            "name": "Rohan Mehta",
            "emails": ["rohan.mehta.testuser@example.com"],
            "phones": ["555-0101"],
            "locations": [{"city": "Detroit", "state": "MI"}],
            "education": [
                {"institution": "University of Michigan", "degree": "MS"},
                {"institution": "Purdue", "degree": "BS"},
            ],
            "employment": [{"company": "Ford", "role": "HIL Simulation"}],
            "skills": ["MATLAB", "Simulink", "HIL", "dSPACE"],
        },
    },
    {
        "slug": "resume_03",
        "text": """Priya Nair TESTUSER
priya.nair.testuser@example.com | +1-555-0102 | Fremont, CA

github.com/priyan-testuser

EDUCATION
Stanford University
PhD in Electrical Engineering, 2018 - 2023

EMPLOYMENT
Tesla - Powertrain Controls Engineer, 2023-08 to Present
- Delivered production Simulink models for e-axle torque management.

Bosch - Controls Intern, 2022-05 to 2022-08

SKILLS
Simulink, MATLAB, C++, Embedded, Model-Based Design
""",
        "expected": {
            "name": "Priya Nair",
            "emails": ["priya.nair.testuser@example.com"],
            "phones": ["555-0102"],
            "locations": [{"city": "Fremont", "state": "CA"}],
            "links": [{"kind": "github", "substring": "priyan-testuser"}],
            "education": [{"institution": "Stanford", "degree": "PhD"}],
            "employment": [
                {"company": "Tesla", "role": "Powertrain Controls"},
                {"company": "Bosch", "role": "Controls Intern"},
            ],
            "skills": ["Simulink", "MATLAB", "C++"],
        },
    },
    {
        "slug": "resume_04",
        "text": """Kevin Park TESTUSER
kevin.park.testuser@example.com | +1-555-0103 | Chandler, AZ

EDUCATION
Arizona State University
BS in Industrial Engineering, 2018 - 2022

EMPLOYMENT
TSMC Arizona - Fab Equipment Engineer, 2022-09 to Present
- Owned uptime and yield for a critical lithography tool.

SKILLS
SPC, PFMEA, Yield Analysis, Preventive Maintenance
""",
        "expected": {
            "name": "Kevin Park",
            "emails": ["kevin.park.testuser@example.com"],
            "phones": ["555-0103"],
            "locations": [{"city": "Chandler", "state": "AZ"}],
            "education": [{"institution": "Arizona State", "degree": "BS"}],
            "employment": [{"company": "TSMC", "role": "Fab Equipment"}],
            "skills": ["SPC", "PFMEA", "Yield Analysis"],
        },
    },
    {
        "slug": "resume_05",
        "text": """Maya Iyer TESTUSER
maya.iyer.testuser@example.com | +1-555-0104 | Mountain View, CA

linkedin.com/in/maya-iyer-testuser

EDUCATION
Carnegie Mellon University
MS in Robotics, 2020 - 2022

EMPLOYMENT
Waymo - Autonomy Systems Engineer, 2022-07 to Present

Applied Intuition - Perception Intern, 2021-05 to 2021-08

SKILLS
Python, ROS, C++, Perception, Motion Planning
""",
        "expected": {
            "name": "Maya Iyer",
            "emails": ["maya.iyer.testuser@example.com"],
            "phones": ["555-0104"],
            "locations": [{"city": "Mountain View", "state": "CA"}],
            "links": [{"kind": "linkedin", "substring": "maya-iyer-testuser"}],
            "education": [{"institution": "Carnegie Mellon", "degree": "MS"}],
            "employment": [
                {"company": "Waymo", "role": "Autonomy Systems"},
                {"company": "Applied Intuition", "role": "Perception"},
            ],
            "skills": ["Python", "ROS", "C++"],
        },
    },
    {
        "slug": "resume_06",
        "text": """Sanya Kapoor TESTUSER
sanya.kapoor.testuser@example.com | +1-555-0105 | Warren, MI

EDUCATION
University of Illinois Urbana-Champaign
BS in Computer Engineering, 2017 - 2021

EMPLOYMENT
General Motors - SIL Software Engineer, 2021-08 to Present
- Automated SIL test-case authoring for ADAS.

SKILLS
Python, SIL, ADAS, TestNG, pytest
""",
        "expected": {
            "name": "Sanya Kapoor",
            "emails": ["sanya.kapoor.testuser@example.com"],
            "phones": ["555-0105"],
            "locations": [{"city": "Warren", "state": "MI"}],
            "education": [{"institution": "Illinois", "degree": "BS"}],
            "employment": [{"company": "General Motors", "role": "SIL Software"}],
            "skills": ["Python", "SIL", "ADAS"],
        },
    },
    {
        "slug": "resume_07",
        "text": """Arjun Desai TESTUSER
arjun.desai.testuser@example.com | +1-555-0106 | Newark, CA

EDUCATION
UC Berkeley
MS in Mechanical Engineering, 2019 - 2021

EMPLOYMENT
Lucid Motors - EV Systems Engineer, 2021-07 to Present
- Coordinated propulsion + HV distribution + thermal requirements for a BEV platform.

SKILLS
EV Systems, HV Distribution, Thermal, Requirements
""",
        "expected": {
            "name": "Arjun Desai",
            "emails": ["arjun.desai.testuser@example.com"],
            "phones": ["555-0106"],
            "locations": [{"city": "Newark", "state": "CA"}],
            "education": [{"institution": "UC Berkeley", "degree": "MS"}],
            "employment": [{"company": "Lucid Motors", "role": "EV Systems"}],
            "skills": ["EV Systems", "Thermal"],
        },
    },
    {
        "slug": "resume_08",
        "text": """Elena Costa TESTUSER
elena.costa.testuser@example.com | +1-555-0107 | Torrance, CA

EDUCATION
Georgia Tech
MS in Systems Engineering, 2018 - 2020

EMPLOYMENT
Honda R&D - Model-Based Systems Engineer, 2020-06 to Present
- Authored SysML models for vehicle-level architectures.

SKILLS
SysML, MBSE, Requirements, Cameo
""",
        "expected": {
            "name": "Elena Costa",
            "emails": ["elena.costa.testuser@example.com"],
            "phones": ["555-0107"],
            "locations": [{"city": "Torrance", "state": "CA"}],
            "education": [{"institution": "Georgia Tech", "degree": "MS"}],
            "employment": [{"company": "Honda", "role": "Model-Based"}],
            "skills": ["SysML", "MBSE"],
        },
    },
    {
        "slug": "resume_09",
        "text": """Deepak Rao TESTUSER
deepak.rao.testuser@example.com | +1-555-0108 | Auburn Hills, MI

EDUCATION
Michigan Tech
BS in Mechanical Engineering, 2015 - 2019

EMPLOYMENT
Aptiv - Vehicle Dynamics Engineer, 2019-06 to Present
- Correlated CarMaker models to proving-ground data.

SKILLS
CarMaker, MATLAB, Vehicle Dynamics
""",
        "expected": {
            "name": "Deepak Rao",
            "emails": ["deepak.rao.testuser@example.com"],
            "phones": ["555-0108"],
            "locations": [{"city": "Auburn Hills", "state": "MI"}],
            "education": [{"institution": "Michigan Tech", "degree": "BS"}],
            "employment": [{"company": "Aptiv", "role": "Vehicle Dynamics"}],
            "skills": ["CarMaker", "MATLAB"],
        },
    },
    {
        "slug": "resume_10",
        "text": """Neha Sharma TESTUSER
neha.sharma.testuser@example.com | +1-555-0109 | Yucca, AZ

EDUCATION
Purdue University
BS in Aerospace Engineering, 2014 - 2018

EMPLOYMENT
Lucid Motors - Vehicle Test Engineer, 2018-08 to Present
- Ran proving-ground DAQ, authored test plans.

SKILLS
DAQ, Test Plans, Vehicle Test, LabVIEW
""",
        "expected": {
            "name": "Neha Sharma",
            "emails": ["neha.sharma.testuser@example.com"],
            "phones": ["555-0109"],
            "locations": [{"city": "Yucca", "state": "AZ"}],
            "education": [{"institution": "Purdue", "degree": "BS"}],
            "employment": [{"company": "Lucid Motors", "role": "Vehicle Test"}],
            "skills": ["DAQ", "LabVIEW"],
        },
    },
]
