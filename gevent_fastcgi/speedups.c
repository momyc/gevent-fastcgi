/*
 * Copyright (c) 2011-2013, Alexander Kulakov
 *
 * Permission is hereby granted, free of charge, to any person obtaining a copy
 * of this software and associated documentation files (the "Software"), to deal
 * in the Software without restriction, including without limitation the rights
 * to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
 * copies of the Software, and to permit persons to whom the Software is
 * furnished to do so, subject to the following conditions:
 *
 *    The above copyright notice and this permission notice shall be included in
 *    all copies or substantial portions of the Software.
 *
 *    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
 *    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
 *    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
 *    AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
 *    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
 *    OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
 *    THE SOFTWARE.
 */

#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <arpa/inet.h>


#define ENSURE_LEN(req) if ((end - buf) < (req)) { \
	Py_XDECREF(result); \
	return PyErr_Format(PyExc_ValueError, "Buffer is %ld byte(s) short", (req) - (end - buf)); \
}

#define PARSE_LEN(len) ENSURE_LEN(1); \
	len = *buf++; \
	if (len & 0x80) { \
		ENSURE_LEN(3); \
		len = ((len & 0x7f) << 24) + (buf[0] << 16) + (buf[1] << 8) + buf[2]; \
		buf += 3; \
	}

static PyObject *
py_unpack_pairs(PyObject *self, PyObject *args) {
	unsigned char *buf, *name, *value, *end;
	Py_ssize_t blen, nlen, vlen;
	PyObject *result, *tuple;

	if (!PyArg_ParseTuple(args, "s#:unpack_pairs", &buf, &blen)) {
		return PyErr_Format(PyExc_ValueError, "Single string argument expected");
	}

	end = buf + blen;
	result = PyList_New(0);

	if (result) {
		while (buf < end) {
			PARSE_LEN(nlen);
			PARSE_LEN(vlen);
			ENSURE_LEN((nlen + vlen));
			name = buf;
			buf += nlen;
			value = buf;
			buf += vlen;
			tuple = Py_BuildValue("(s#s#)", name, nlen, value, vlen);
			if (tuple) {
				PyList_Append(result, tuple);
				Py_DECREF(tuple);
			} else {
				Py_XDECREF(result);
				return PyErr_Format(PyExc_RuntimeError, "Failed to allocate memory for next name/value tuple");
			}
		}
	}

	return result;
}

#define PACK_LEN(len) if (len > 127) { \
		*ptr++ = 0x80 + ((len >> 24) & 0xff); \
		*ptr++ = (len >> 16) & 0xff; \
		*ptr++ = (len >> 8) & 0xff; \
		*ptr++ = len & 0xff; \
	} else { \
		*ptr++ = len; \
	}

static PyObject *
py_pack_pair(PyObject *self, PyObject *args) {
	PyObject *result, *name, *value;
	unsigned char *buf, *ptr;
	Py_ssize_t name_len, value_len, buf_len;

	if (!PyArg_ParseTuple(args, "s#s#:pack_pair", &name, &name_len, &value, &value_len)) {
		return NULL;
	}

	if (name_len > 0x7fffffff) {
		PyErr_SetString (PyExc_ValueError,"Pair name too long");
		return NULL;
	}

	if (value_len > 0x7fffffff) {
		PyErr_SetString (PyExc_ValueError,"Pair value too long");
		return NULL;
	}


	buf_len = name_len + value_len + (name_len > 127 ? 4 : 1) + (value_len > 127 ? 4 : 1);
	buf = ptr = (unsigned char*) PyMem_Malloc(buf_len);

	if (!buf) return PyErr_NoMemory();

	PACK_LEN(name_len);
	PACK_LEN(value_len);
	memcpy(ptr, name, name_len);
	memcpy(ptr + name_len, value, value_len);

	result = PyString_FromStringAndSize(buf, buf_len);
	PyMem_Free(buf);
	
	return result;
}

typedef struct {
	unsigned char fcgi_version, record_type;
	unsigned short int request_id, content_len;
	unsigned char padding;
	char reserved;
} record_header_t;


static PyObject *
py_pack_header(PyObject *self, PyObject *args) {
	PyObject *result;
	record_header_t *header;

	header = (record_header_t *) PyMem_Malloc(sizeof(record_header_t));
	if (!header) return PyErr_NoMemory();

	if (!PyArg_ParseTuple(args, "bbHHb:pack_header",
		&(header->fcgi_version),
		&(header->record_type),
		&(header->request_id),
		&(header->content_len),
		&(header->padding))) return NULL;

	header->request_id = htons(header->request_id);
	header->content_len = htons(header->content_len);

	result = PyString_FromStringAndSize((char *)header, sizeof(record_header_t));
	PyMem_Free(header);
	return result;
}


static PyObject *
py_unpack_header(PyObject *self, PyObject *args) {
	PyObject *result;
	record_header_t *header;
	Py_ssize_t len;
	
	if (!PyArg_ParseTuple(args, "s#:unpack_header", (char *)&header, &len)) return NULL;

	if (len < sizeof(record_header_t))
		return PyErr_Format(PyExc_ValueError,
				"Data must be at least %ld bytes long (%ld passed)",
				sizeof(record_header_t), len);

	result = Py_BuildValue("(bbhhb)",
			header->fcgi_version,
			header->record_type,
			ntohs(header->request_id),
			ntohs(header->content_len),
			header->padding);
	if (!result) return PyErr_NoMemory();
	PyMem_Free(header);
	return result;
}


static PyMethodDef _methods[] = {
	{"unpack_pairs", py_unpack_pairs, METH_VARARGS},
	{"pack_pair", py_pack_pair, METH_VARARGS},
	{"pack_header", py_pack_header, METH_VARARGS},
	{"unpack_header", py_unpack_header, METH_VARARGS},
	{NULL, NULL}
};

PyMODINIT_FUNC
initspeedups(void) {
	Py_InitModule("speedups", _methods);
}
