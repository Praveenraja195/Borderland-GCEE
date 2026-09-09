"""update trg_jh_validate to fire BEFORE INSERT OR UPDATE

Revision ID: 0007
Revises: 0006
Create Date: 2026-08-15

"""

from typing import Sequence, Union
from alembic import op

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_jh_validate ON jack_heart_answers;")
    op.execute(
        """
        CREATE TRIGGER trg_jh_validate
        BEFORE INSERT OR UPDATE ON jack_heart_answers
        FOR EACH ROW EXECUTE FUNCTION fn_validate_jh_answer();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_jh_validate ON jack_heart_answers;")
    op.execute(
        """
        CREATE TRIGGER trg_jh_validate
        BEFORE INSERT ON jack_heart_answers
        FOR EACH ROW EXECUTE FUNCTION fn_validate_jh_answer();
        """
    )
