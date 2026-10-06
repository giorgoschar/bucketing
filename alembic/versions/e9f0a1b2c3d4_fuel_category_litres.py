"""built-in Fuel category and litres on transactions

- categories.system_key VARCHAR(32) NULL, unique per household
  (uq_categories_household_system_key): marks the categories the app relies
  on, which are locked against edits. 'fuel' is the only key so far.
- transactions.fuel_price_per_litre NUMERIC(8,4) NULL and
  transactions.fuel_litres NUMERIC(10,3) NULL: set only on fuel expenses; the
  litres are stored (amount / price) so they aggregate in SQL.

Categories belong to a household (app.seed copies the defaults into each), so
every existing household gets its own Fuel category here. A category it
already keeps fuel under ("Fuel", "Καύσιμα", ... the same list as
app.seed.FUEL_LIKE_NAMES) is adopted instead of getting a twin.

Downgrade drops the columns only: the seeded Fuel rows stay as ordinary
categories, since expenses may point at them.

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-10-05 18:00:00.000000

"""
import uuid

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = 'e9f0a1b2c3d4'
down_revision = 'd8e9f0a1b2c3'
branch_labels = None
depends_on = None

UNIQUE_NAME = 'uq_categories_household_system_key'
FUEL = 'fuel'
# Frozen copy of app.seed.FUEL_LIKE_NAMES: a migration must not import app code.
# Most preferred first; no 'gas', which is as often the natural-gas utility.
FUEL_LIKE_NAMES = (
    'fuel', 'καύσιμα', 'καυσιμα',
    'petrol', 'gasoline', 'diesel', 'βενζίνη', 'βενζινη',
)


def _seed_fuel(conn) -> None:
    """One fuel category per household: adopt a fuel-like one, else add it.

    Matched in Python: SQLite's lower() leaves Greek letters alone. With
    several matches the earliest name in FUEL_LIKE_NAMES wins ("Fuel" over
    "Diesel"), then the rows' own order.
    """
    households = [r[0] for r in conn.execute(sa.text('SELECT id FROM households'))]
    cats = conn.execute(sa.text(
        'SELECT id, household_id, name FROM categories WHERE household_id IS NOT NULL '
        'ORDER BY name, id'
    )).all()
    best: dict[str, tuple[int, str]] = {}
    for cat_id, hh_id, name in cats:
        key = (name or '').strip().lower()
        if key in FUEL_LIKE_NAMES:
            rank = FUEL_LIKE_NAMES.index(key)
            if hh_id not in best or rank < best[hh_id][0]:
                best[hh_id] = (rank, cat_id)
    fuel_like = {hh_id: cat_id for hh_id, (_, cat_id) in best.items()}

    for hh_id in households:
        if hh_id in fuel_like:
            conn.execute(
                sa.text('UPDATE categories SET system_key = :k WHERE id = :i'),
                {'k': FUEL, 'i': fuel_like[hh_id]},
            )
        else:
            conn.execute(
                sa.text(
                    'INSERT INTO categories (id, household_id, name, color, icon, is_default, system_key) '
                    'VALUES (:i, :h, :n, :c, :ic, :d, :k)'
                ),
                {'i': str(uuid.uuid4()), 'h': hh_id, 'n': 'Fuel', 'c': '#ea580c',
                 'ic': '⛽', 'd': True, 'k': FUEL},
            )


def upgrade() -> None:
    conn = op.get_bind()
    if conn.dialect.name == 'postgresql':
        op.add_column('categories', sa.Column('system_key', sa.String(length=32), nullable=True))
        op.create_unique_constraint(UNIQUE_NAME, 'categories', ['household_id', 'system_key'])
    else:
        # SQLite cannot add a constraint with ALTER TABLE: batch mode copies the table.
        with op.batch_alter_table('categories') as batch:
            batch.add_column(sa.Column('system_key', sa.String(length=32), nullable=True))
            batch.create_unique_constraint(UNIQUE_NAME, ['household_id', 'system_key'])

    with op.batch_alter_table('transactions') as batch:
        batch.add_column(sa.Column('fuel_price_per_litre', sa.Numeric(8, 4), nullable=True))
        batch.add_column(sa.Column('fuel_litres', sa.Numeric(10, 3), nullable=True))

    _seed_fuel(conn)


def downgrade() -> None:
    conn = op.get_bind()
    with op.batch_alter_table('transactions') as batch:
        batch.drop_column('fuel_litres')
        batch.drop_column('fuel_price_per_litre')

    if conn.dialect.name == 'postgresql':
        op.drop_constraint(UNIQUE_NAME, 'categories', type_='unique')
        op.drop_column('categories', 'system_key')
    else:
        with op.batch_alter_table('categories') as batch:
            batch.drop_constraint(UNIQUE_NAME, type_='unique')
            batch.drop_column('system_key')
