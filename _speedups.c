#include <Python.h>

#define ENSURE_LEN(req) if (end - buf < req) return PyErr_Format(PyExc_ValueError, "Buffer is %d byte(s) short", req)
#define PARSE_LEN(len) ENSURE_LEN(1); \
	len = *buf++; \
	if (len & 0x80) { \
		ENSURE_LEN(3); \
		len = (len & 0x7f) << 24 + (*buf++) << 16 + (*buf++) << 8 + (*buf++); \
	}

static PyObject *
py_unpack_pairs(PyObject *self, PyObject *args) {
	const char *buf, *name, *value, *end;
	int blen, nlen, vlen;
	PyObject *result, *tuple;

	if (!PyArg_ParseTuple(args, "s#:unpack_pairs", &buf, &blen)) {
		return PyErr_Format(PyExc_ValueError, "Single string argument expected");
	}

	end = buf + blen;
	result = PyList_New(0);

	if (!result)
		return PyErr_Format(PyExc_RuntimeError, "Unable to allocate list");;

	while (buf < end) {
		PARSE_LEN(nlen);
		PARSE_LEN(vlen);
		ENSURE_LEN(nlen + vlen);
		name = buf;
		buf += nlen;
		value = buf;
		buf += vlen;
		tuple = Py_BuildValue("s#s#", name, nlen, value, vlen);
		if (tuple) {
			PyList_Append(result, tuple);
			Py_DECREF(tuple);
		}
	}

	return result;
}

/*
static PyObject *
py_pack_pairs(PyObject *self, PyObject *args) {
	PyObject *result, *pairs, *pair;
	int i;

	if (!PyArg_ParseTuple(args, "(s#s#):pack_pairs", &pairs)) {
		return NULL;
	}

	result = PyList_New(0);
	for (i=0;;i++) {
		pair = PySequence_GetItem(pairs, i);
		if (!pair) break;
		PyList_Append(result, PyBuild_Value("s#s#
	}

	return NULL;
}
*/

static PyMethodDef _methods[] = {
	{"unpack_pairs", py_unpack_pairs, METH_VARARGS},
	{NULL, NULL}
};

PyMODINIT_FUNC
init_speedups(void) {
	Py_InitModule("_speedups", _methods);
}
