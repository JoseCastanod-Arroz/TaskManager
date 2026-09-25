"""Paquete de pruebas de TaskManager (feature: external-data-api).

Contiene:
- conftest.py: utilidades compartidas (base SQLite temporal, fixtures de
  Flask y de conexión) reutilizables por las pruebas unitarias y de propiedad.
- strategies.py: estrategias base de Hypothesis (usuarios, tareas, subtareas,
  eventos) reutilizables en las pruebas basadas en propiedades.
"""
