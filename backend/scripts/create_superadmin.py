"""
Crea el primer usuario superadministrador del sistema.

Uso:
    python -m scripts.create_superadmin
    python -m scripts.create_superadmin --username admin --email admin@agas.cl \
        --password "MiClave123!" --rut "12.345.678-9"

Si no se proporciona contraseña, se genera una aleatoria y se muestra en pantalla.
El usuario nace con estado ACTIVO, requiere_cambio_password=True y con las
tareas de dominio RBAC (TAREA_28/29/30 + TAREA_01/02/03/15/16 de maestros
e inventario) asignadas
a su empleado; si los
catálogos aún no existen se avisa (requiere scripts/seed_data.py).
"""

from __future__ import annotations

import argparse
import asyncio
import secrets
import string
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.security import hash_password
from app.database import async_session_factory, close_db, init_db
from app.models import Area, Empleado, EmpleadoTarea, Tarea, Usuario

# Tareas de dominio del RBAC (scripts/seed_data.py): sin ellas el superadmin
# recibiría 403 en todos los módulos de la API. TAREA_01/02 cubren los
# maestros de la ETAPA 4.1 (clientes, receptores y propietarios), TAREA_03/15/16
# la ETAPA 4.2 (cilindros, ubicaciones y movimientos) y TAREA_04 la ETAPA 5.1
# (recepción de cilindros).
TAREAS_SUPERADMIN = (
    "TAREA_01",
    "TAREA_02",
    "TAREA_03",
    "TAREA_04",
    "TAREA_15",
    "TAREA_16",
    "TAREA_28",
    "TAREA_29",
    "TAREA_30",
)


async def asegurar_tareas_superadmin(session, usuario: Usuario) -> None:
    """Asigna (o reactiva) las tareas de dominio del superadmin.

    Idempotente: si la fila ya existe y está VIGENTE solo lo informa. Si los
    catálogos no están sembrados aún, avisa en lugar de fallar.
    """
    if usuario.empleado_id is None:
        print("  ⚠️  Sin empleado vinculado: no se pueden asignar tareas RBAC")
        return
    for codigo in TAREAS_SUPERADMIN:
        tarea = (
            await session.execute(select(Tarea).where(Tarea.codigo == codigo))
        ).scalar_one_or_none()
        if tarea is None:
            print(f"  ⚠️  {codigo} no existe (ejecute scripts/seed_data.py primero)")
            continue
        fila = (
            await session.execute(
                select(EmpleadoTarea).where(
                    EmpleadoTarea.empleado_id == usuario.empleado_id,
                    EmpleadoTarea.tarea_id == tarea.id,
                )
            )
        ).scalars().first()
        if fila is None:
            session.add(
                EmpleadoTarea(
                    empleado_id=usuario.empleado_id,
                    tarea_id=tarea.id,
                    usuario_asigno_id=usuario.id,
                )
            )
            print(f"  ✓ Tarea asignada: {codigo}")
        elif fila.estado != "VIGENTE":
            fila.estado = "VIGENTE"
            fila.fecha_termino = None
            print(f"  ✓ Tarea reactivada: {codigo}")
        else:
            print(f"  ✓ Tarea ya vigente: {codigo}")


def generate_password(length: int = 16) -> str:
    """Genera contraseña aleatoria que cumple la política de seguridad."""
    lowers = string.ascii_lowercase
    uppers = string.ascii_uppercase
    digits = string.digits
    specials = "!@#$%^&*"

    # Garantiza al menos un carácter de cada tipo
    pwd = [
        secrets.choice(uppers),
        secrets.choice(lowers),
        secrets.choice(digits),
        secrets.choice(specials),
    ]
    # Rellena el resto
    remaining = length - len(pwd)
    all_chars = lowers + uppers + digits + specials
    pwd.extend(secrets.choice(all_chars) for _ in range(remaining))
    # Mezcla
    secrets.SystemRandom().shuffle(pwd)
    return "".join(pwd)


async def create_superadmin(
    username: str = "admin",
    email: str = "admin@agas.cl",
    password: str | None = None,
    rut: str = "00.000.000-0",
    nombres: str = "Super",
    apellidos: str = "Administrador",
) -> None:
    """Crea empleado + usuario superadmin si no existe."""

    async with async_session_factory() as session:
        # Verificar si ya existe un superadmin
        existing = await session.execute(select(Usuario).where(Usuario.username == username))
        existente = existing.scalar_one_or_none()
        if existente:
            print(f"⚠️  El usuario '{username}' ya existe. No se crea nada,")
            print("    pero se asegura que tenga sus tareas RBAC:")
            await asegurar_tareas_superadmin(session, existente)
            await session.commit()
            return

        # Verificar si ya existe un admin activo
        existing_active = await session.execute(select(Usuario).where(Usuario.estado == "ACTIVO"))
        if existing_active.scalar_one_or_none() and username == "admin":
            print("⚠️  Ya existe al menos un usuario ACTIVO.")
            confirm = input("¿Desea crear OTRO usuario admin? (s/N): ").strip().lower()
            if confirm != "s":
                print("Cancelado.")
                return

        # Buscar o crear área de Administración
        result = await session.execute(select(Area).where(Area.codigo == "ADM"))
        area = result.scalar_one_or_none()
        if not area:
            area = Area(codigo="ADM", nombre="Administración", orden_visual=7)
            session.add(area)
            await session.flush()
            print("  ✓ Área Administración creada")

        # Crear empleado
        empleado = Empleado(
            rut=rut,
            nombres=nombres,
            apellidos=apellidos,
            cargo="Superadministrador",
            area_id=area.id,
            correo=email,
            fecha_ingreso=__import__("datetime").date.today(),
            estado="ACTIVO",
            observaciones="Usuario inicial del sistema",
        )
        session.add(empleado)
        await session.flush()
        print(f"  ✓ Empleado creado: {nombres} {apellidos} ({rut})")

        # Generar o usar contraseña
        if password is None:
            password = generate_password()
            generated = True
        else:
            generated = False

        # Crear usuario
        usuario = Usuario(
            empleado_id=empleado.id,
            username=username,
            email=email,
            password_hash=hash_password(password),
            estado="ACTIVO",
            requiere_cambio_password=True,
        )
        session.add(usuario)
        await session.flush()
        print(f"  ✓ Usuario creado: {username}")

        # RBAC: el superadmin nace con los tres dominios asignados.
        await asegurar_tareas_superadmin(session, usuario)

        await session.commit()

    print("\n" + "=" * 60)
    print("  SUPERADMIN CREADO EXITOSAMENTE")
    print("=" * 60)
    print(f"  Usuario:    {username}")
    print(f"  Email:      {email}")
    print(f"  RUT:        {rut}")
    if generated:
        print(f"  Contraseña: {password}")
    else:
        print("  Contraseña: (la proporcionada)")
    print("  Estado:     ACTIVO")
    print("  Cambio pw:  SÍ (debe cambiar en primer ingreso)")
    print("=" * 60)
    if generated:
        print("  ⚠️  GUARDE ESTA CONTRASEÑA. No se volverá a mostrar.")
    print("=" * 60)


async def main() -> None:
    parser = argparse.ArgumentParser(description="Crear superadministrador del sistema")
    parser.add_argument("--username", default="admin", help="Nombre de usuario (default: admin)")
    parser.add_argument("--email", default="admin@agas.cl", help="Correo electrónico")
    parser.add_argument("--password", default=None, help="Contraseña (se genera si no se indica)")
    parser.add_argument("--rut", default="00.000.000-0", help="RUT del empleado")
    parser.add_argument("--nombres", default="Super", help="Nombres")
    parser.add_argument("--apellidos", default="Administrador", help="Apellidos")
    args = parser.parse_args()

    await init_db()
    await create_superadmin(
        username=args.username,
        email=args.email,
        password=args.password,
        rut=args.rut,
        nombres=args.nombres,
        apellidos=args.apellidos,
    )
    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
