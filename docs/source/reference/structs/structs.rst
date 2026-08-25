Records: structs, plans and fields
==================================

:mod:`bytemaker.structs` is the headline API: declare a record class with
annotated fields, then :py:meth:`~bytemaker.structs.Struct.parse` bytes into
plain Python values and :py:meth:`~bytemaker.structs.Struct.pack` them back.
:mod:`bytemaker.plans` is the layout compiler behind it, and
:mod:`bytemaker.fields` provides the ``u8``/``s16``-style field aliases.

structs
^^^^^^^

.. automodule:: bytemaker.structs
   :members:
   :undoc-members:
   :show-inheritance:

plans
^^^^^

.. automodule:: bytemaker.plans
   :members:
   :undoc-members:
   :show-inheritance:

fields
^^^^^^

.. automodule:: bytemaker.fields
   :members:
   :undoc-members:
   :show-inheritance:
