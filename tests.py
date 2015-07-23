import errno
import imp
import io
import json
import os
import sys
import textwrap
# try:
#     import configparser  # py3
# except ImportError:
#     import ConfigParser as configparser

import confix
from confix import Error, UnrecognizedKeyError, RequiredKeyError
from confix import istrue, isin, isnotin, isemail, get_parsed_conf
from confix import register, parse, parse_with_envvars, discard, schema
from confix import TypesMismatchError, AlreadyParsedError, NotParsedError
from confix import ValidationError, AlreadyRegisteredError

try:
    import toml
except ImportError:
    toml = None
try:
    import yaml
except ImportError:
    yaml = None

PY3 = sys.version_info >= (3, )
# if PY3:
#     import io
#     StringIO = io.StringIO
# else:
#     from StringIO import StringIO

if sys.version_info >= (2, 7):
    import unittest
else:
    import unittest2 as unittest  # requires 'pip install unittest2'


THIS_MODULE = os.path.splitext(os.path.basename(__file__))[0]
TESTFN = '$testfile'


def unlink(path):
    try:
        os.remove(path)
    except OSError as err:
        if err.errno != errno.ENOENT:
            raise


# ===================================================================
# base class
# ===================================================================


class BaseMixin(object):
    """Base class from which mixin classes are derived."""
    TESTFN = None

    def setUp(self):
        self.original_environ = os.environ.copy()

    def tearDown(self):
        discard()
        os.environ = self.original_environ
        unlink(self.TESTFN)

    @classmethod
    def tearDownClass(cls):
        unlink(TESTFN)

    # --- utils

    def dict_to_file(self, dct):
        raise NotImplementedError('must be implemented in subclass')

    @classmethod
    def write_to_file(cls, content, fname=None):
        with open(fname or cls.TESTFN, 'w') as f:
            f.write(content)

    # --- base tests

    def test_empty_conf_file(self):
        @register()
        class config:
            foo = 1
            bar = 2

        self.write_to_file("   ")
        parse(self.TESTFN)
        self.assertEqual(config.foo, 1)
        self.assertEqual(config.bar, 2)

    def test_conf_file_overrides_key(self):
        # Conf file overrides one key, other one should be default.
        @register()
        class config:
            foo = 1
            bar = 2

        self.dict_to_file(
            dict(foo=5)
        )
        parse(self.TESTFN)
        self.assertEqual(config.foo, 5)
        self.assertEqual(config.bar, 2)

    def test_conf_file_overrides_all_keys(self):
        # Conf file overrides both keys.
        @register()
        class config:
            foo = 1
            bar = 2

        self.dict_to_file(
            dict(foo=5, bar=6)
        )
        parse(self.TESTFN)
        self.assertEqual(config.foo, 5)
        self.assertEqual(config.bar, 6)

    def test_unrecognized_key(self):
        # Conf file has a key which is not specified in the config class.
        @register()
        class config:
            foo = 1
            bar = 2

        self.dict_to_file(
            dict(foo=5, apple=6)
        )
        with self.assertRaises(UnrecognizedKeyError) as cm:
            parse(self.TESTFN)
        # self.assertEqual(cm.exception.section, 'name')  # TODO
        self.assertEqual(cm.exception.key, 'apple')

    def test_types_mismatch(self):
        # Conf file provides a key with a value whose type is != than
        # conf class default type.
        @register()
        class config:
            foo = 1
            bar = 2

        self.dict_to_file(
            dict(foo=5, bar='6')
        )
        with self.assertRaises(TypesMismatchError) as cm:
            parse(self.TESTFN)
        # self.assertEqual(cm.exception.section, 'name')
        self.assertEqual(cm.exception.key, 'bar')
        self.assertEqual(cm.exception.default_value, 2)
        self.assertEqual(cm.exception.new_value, '6')

        # ...Unless we explicitly tell parse() to ignore type mismatch.
        parse(self.TESTFN, type_check=False)
        self.assertEqual(config.foo, 5)
        self.assertEqual(config.bar, '6')

    # def test_invalid_yaml_file(self):
    #     self.dict_to_file('?!?')
    #     with self.assertRaises(Error) as cm:
    #         parse(self.TESTFN)

    # --- test schemas

    def test_schema_base(self):
        # A schema with no constraints is supposed to be converted into
        # its default value after parse().
        @register()
        class config:
            foo = schema(10)

        self.dict_to_file({})
        parse(self.TESTFN)
        self.assertEqual(config.foo, 10)

    def test_schema_required(self):
        # If a schema is required and it's not specified in the config
        # file expect an error.
        @register()
        class config:
            foo = schema(10, required=True)
            bar = 2

        self.dict_to_file(
            dict(bar=2)
        )
        with self.assertRaises(RequiredKeyError) as cm:
            parse(self.TESTFN)
        # self.assertEqual(cm.exception.section, 'name')  # TODO
        self.assertEqual(cm.exception.key, 'foo')

    def test_schema_required_provided(self):
        # If a schema is required and it's provided in the conf file
        # eveything is cool.
        @register()
        class config:
            foo = schema(10, required=True)

        self.dict_to_file(
            dict(foo=5)
        )
        parse(self.TESTFN)
        self.assertEqual(config.foo, 5)

    def test_schemas_w_multi_validators(self):
        def fun1(x):
            flags.append(1)
            return True

        def fun2(x):
            flags.append(2)
            return True

        def fun3(x):
            flags.append(3)
            return True

        def fun4(x):
            flags.append(4)
            return True

        @register()
        class config:
            overridden = schema(10, validator=[fun1, fun2])
            not_overridden = schema(10, validator=[fun3, fun4])

        flags = []
        self.dict_to_file(
            dict(overridden=5)
        )
        parse(self.TESTFN)
        self.assertEqual(sorted(flags), [1, 2, 3, 4])
        self.assertEqual(config.overridden, 5)
        self.assertEqual(config.not_overridden, 10)

    # --- test validators

    def test_validator_ok(self):
        @register()
        class config:
            foo = schema(10, validator=lambda x: isinstance(x, int))

        self.dict_to_file(
            dict(foo=5)
        )
        parse(self.TESTFN)

    def test_validator_ko(self):
        @register()
        class config:
            foo = schema(10, validator=lambda x: isinstance(x, str))

        self.dict_to_file(
            dict(foo=5)
        )
        with self.assertRaises(ValidationError) as cm:
            parse(self.TESTFN)
        # self.assertEqual(cm.exception.section, 'name')  # TODO
        self.assertEqual(cm.exception.key, 'foo')
        self.assertEqual(cm.exception.value, 5)

    def test_validator_ko_custom_exc_w_message(self):
        def validator(value):
            raise ValidationError('message')

        @register()
        class config:
            foo = schema(10, validator=validator)
        self.dict_to_file(
            dict(foo=5)
        )

        with self.assertRaises(ValidationError) as cm:
            parse(self.TESTFN)
        # self.assertEqual(cm.exception.section, 'name')  # TODO
        self.assertEqual(cm.exception.key, 'foo')
        self.assertEqual(cm.exception.value, 5)
        self.assertEqual(cm.exception.msg, 'message')

    def test_validator_ko_custom_exc_w_no_message(self):
        def validator(value):
            raise ValidationError

        @register()
        class config:
            foo = schema(10, validator=validator)
        self.dict_to_file(
            dict(foo=5)
        )

        with self.assertRaises(ValidationError) as cm:
            parse(self.TESTFN)
        # self.assertEqual(cm.exception.section, 'name')  # TODO
        self.assertEqual(cm.exception.key, 'foo')
        self.assertEqual(cm.exception.value, 5)
        self.assertEqual(cm.exception.msg, None)
        self.assertIn('with value 5', str(cm.exception))

    # --- test parse_with_envvars

    def test_envvars_base(self):
        @register()
        class config:
            foo = 1
            bar = 2
            apple = 3

        self.dict_to_file(
            dict(foo=5)
        )
        os.environ['APPLE'] = '10'
        parse_with_envvars(self.TESTFN)
        self.assertEqual(config.foo, 5)
        self.assertEqual(config.bar, 2)
        self.assertEqual(config.apple, 10)

    def test_envvars_base_case_sensitive(self):
        @register()
        class config:
            foo = 1
            bar = 2
            apple = 3

        self.dict_to_file(
            dict(foo=5)
        )
        os.environ['APPLE'] = '10'
        parse_with_envvars(self.TESTFN, case_sensitive=True)
        self.assertEqual(config.foo, 5)
        self.assertEqual(config.bar, 2)
        self.assertEqual(config.apple, 3)

    def test_envvars_convert_type(self):
        @register()
        class config:
            some_int = 1
            some_float = 1.0
            some_true_bool = True
            some_false_bool = True

        os.environ['SOME_INT'] = '2'
        os.environ['SOME_FLOAT'] = '2.0'
        os.environ['SOME_TRUE_BOOL'] = 'false'
        os.environ['SOME_FALSE_BOOL'] = 'true'
        parse_with_envvars()
        self.assertEqual(config.some_int, 2)
        self.assertEqual(config.some_float, 2.0)
        self.assertEqual(config.some_true_bool, False)
        self.assertEqual(config.some_false_bool, True)

    def test_envvars_convert_type_w_schema(self):
        @register()
        class config:
            some_int = schema(1)

        os.environ['SOME_INT'] = '2'
        parse_with_envvars()
        self.assertEqual(config.some_int, 2)

    def test_envvars_type_mismatch(self):
        @register()
        class config:
            some_int = 1
            some_float = 0.1
            some_bool = True

        # int
        os.environ['SOME_INT'] = 'foo'
        with self.assertRaises(TypesMismatchError) as cm:
            parse_with_envvars()
        # self.assertEqual(cm.exception.section, 'name')
        self.assertEqual(cm.exception.key, 'some_int')
        self.assertEqual(cm.exception.default_value, 1)
        self.assertEqual(cm.exception.new_value, 'foo')
        del os.environ['SOME_INT']

        # float
        os.environ['SOME_FLOAT'] = 'foo'
        with self.assertRaises(TypesMismatchError) as cm:
            parse_with_envvars()
        # self.assertEqual(cm.exception.section, 'name')
        self.assertEqual(cm.exception.key, 'some_float')
        self.assertEqual(cm.exception.default_value, 0.1)
        self.assertEqual(cm.exception.new_value, 'foo')
        del os.environ['SOME_FLOAT']

        # bool
        os.environ['SOME_BOOL'] = 'foo'
        with self.assertRaises(TypesMismatchError) as cm:
            parse_with_envvars()
        # self.assertEqual(cm.exception.section, 'name')
        self.assertEqual(cm.exception.key, 'some_bool')
        self.assertEqual(cm.exception.default_value, True)
        self.assertEqual(cm.exception.new_value, 'foo')

    # --- test multiple sections

    def test_multisection_multiple(self):
        # Define two configuration classes, control them via a single
        # conf file defining separate sections.
        @register('ftp')
        class ftp_config:
            port = 21
            username = 'ftp'

        @register('http')
        class http_config:
            port = 80
            username = 'www'

        self.dict_to_file({
            'ftp': dict(username='foo'),
            'http': dict(username='bar'),
        })
        parse(self.TESTFN)
        self.assertEqual(ftp_config.port, 21)
        self.assertEqual(ftp_config.username, 'foo')
        self.assertEqual(http_config.port, 80)
        self.assertEqual(http_config.username, 'bar')

    def test_multisection_invalid_section(self):
        # Config file define a section which is not defined in config
        # class.
        @register('ftp')
        class config:
            port = 21
            username = 'ftp'

        self.dict_to_file({
            'http': dict(username='bar'),
        })
        with self.assertRaises(UnrecognizedKeyError) as cm:
            parse(self.TESTFN)
        self.assertEqual(cm.exception.key, 'http')
        self.assertEqual(cm.exception.value, dict(username='bar'))
        self.assertEqual(cm.exception.section, None)

    def test_multisection_unrecognized_key(self):
        # Config file define a section key which is not defined in config
        # class.
        @register('ftp')
        class config:
            port = 21
            username = 'ftp'

        self.dict_to_file({
            'ftp': dict(password='bar'),
        })
        with self.assertRaises(UnrecognizedKeyError) as cm:
            parse(self.TESTFN)
        self.assertEqual(cm.exception.key, 'password')
        self.assertEqual(cm.exception.value, 'bar')
        self.assertEqual(cm.exception.section, 'ftp')


# ===================================================================
# mixin tests
# ===================================================================


@unittest.skipUnless(yaml is not None, "yaml module is not installed")
class TestYamlMixin(BaseMixin, unittest.TestCase):
    TESTFN = TESTFN + '.yaml'

    def dict_to_file(self, dct):
        s = yaml.dump(dct, default_flow_style=False)
        self.write_to_file(s)


class TestJsonMixin(BaseMixin, unittest.TestCase):
    TESTFN = TESTFN + '.json'

    def dict_to_file(self, dct):
        self.write_to_file(json.dumps(dct))


@unittest.skipUnless(toml is not None, "toml module is not installed")
class TestTomlMixin(BaseMixin, unittest.TestCase):
    TESTFN = TESTFN + '.toml'

    def dict_to_file(self, dct):
        s = toml.dumps(dct)
        self.write_to_file(s)


# TODO: see what to do with root section and re-enable this

# class TestIniMixin(BaseMixin, unittest.TestCase):
#     TESTFN = TESTFN + 'testfile.ini'

    # def dict_to_file(self, dct):
    #     config = configparser.RawConfigParser()
    #     for section, values in dct.items():
    #         assert isinstance(section, str)
    #         config.add_section(section)
    #         for key, value in values.items():
    #             config.set(section, key, value)
    #     fl = StringIO()
    #     config.write(fl)
    #     fl.seek(0)
    #     content = fl.read()
    #     self.write_to_file(content)


# ===================================================================
# tests for a specific format
# ===================================================================


class TestIni(unittest.TestCase):
    TESTFN = TESTFN + '.ini'

    def tearDown(self):
        discard()
        unlink(self.TESTFN)

    def write_to_file(self, content):
        with open(self.TESTFN, 'w') as f:
            f.write(content)

    # XXX: should this test be common to all formats?
    def test_int_ok(self):
        @register('name')
        class config:
            foo = 1
            bar = 2

        self.write_to_file(textwrap.dedent("""
            [name]
            foo = 9
        """))
        parse(self.TESTFN)
        self.assertEqual(config.foo, 9)

    # XXX: should this test be common to all formats?
    def test_int_ko(self):
        @register('name')
        class config:
            foo = 1
            bar = 2

        self.write_to_file(textwrap.dedent("""
            [name]
            foo = '9'
        """))
        self.assertRaises(TypesMismatchError, parse, self.TESTFN)

    def test_float(self):
        @register('name')
        class config:
            foo = 1.1
            bar = 2

        self.write_to_file(textwrap.dedent("""
            [name]
            foo = 1.3
        """))
        parse(self.TESTFN)
        self.assertEqual(config.foo, 1.3)

    def test_true(self):
        true_values = ("1", "yes", "true", "on")
        for value in true_values:
            @register('name')
            class config:
                foo = None
                bar = 2

            self.write_to_file(textwrap.dedent("""
                [name]
                foo = %s
            """ % (value)))
            parse(self.TESTFN)
            self.assertEqual(config.foo, True)
            discard()

    def test_false(self):
        true_values = ("0", "no", "false", "off")
        for value in true_values:
            @register('name')
            class config:
                foo = None
                bar = 2

            self.write_to_file(textwrap.dedent("""
                [name]
                foo = %s
            """ % (value)))
            parse(self.TESTFN)
            self.assertEqual(config.foo, False)
            discard()


# ===================================================================
# test validators
# ===================================================================


class TestValidators(unittest.TestCase):

    def test_istrue(self):
        assert istrue('foo')
        self.assertRaises(ValidationError, istrue, '')

    def test_isin(self):
        self.assertRaises(TypeError, isin, 1)
        fun = isin(('1', '2'))
        assert fun('1')
        assert fun('2')
        self.assertRaises(ValidationError, fun, '3')
        self.assertRaises(ValueError, isin, [])

    def test_isnotin(self):
        self.assertRaises(TypeError, isin, 1)
        fun = isnotin(('1', '2'))
        assert fun('3')
        assert fun('4')
        self.assertRaises(ValidationError, fun, '2')
        self.assertRaisesRegexp(
            TypeError, "is not iterable", isnotin, None)
        self.assertRaisesRegexp(
            ValueError, "sequence can't be empty", isnotin, [])

    def test_isemail(self):
        assert isemail("foo@bar.com")
        assert isemail("foo@gmail.bar.com")
        self.assertRaises(ValidationError, isemail, "@bar.com")
        self.assertRaises(ValidationError, isemail, "foo@bar")
        self.assertRaises(ValidationError, isemail, "foo@bar.")
        self.assertRaisesRegexp(
            ValidationError, "expected a string", isemail, None)
        assert isemail("email@domain.com")
        assert isemail("\"email\"@domain.com")
        assert isemail("firstname.lastname@domain.com")
        assert isemail("email@subdomain.domain.com")
        assert isemail("firstname+lastname@domain.com")
        assert isemail("email@123.123.123.123")
        assert isemail("email@[123.123.123.123]")
        assert isemail("1234567890@domain.com")
        assert isemail("email@domain-one.com")
        assert isemail("_______@domain.com")
        assert isemail("email@domain.name")
        assert isemail("email@domain.co.jp")
        assert isemail("firstname-lastname@domain.com")


# ===================================================================
# parse() tests
# ===================================================================


class TestParse(unittest.TestCase):

    def setUp(self):
        discard()
    tearDown = setUp

    def test_no_conf_file(self):
        # parse() is supposed to parse also if no conf file is passed
        @register()
        class config:
            foo = 1
            bar = schema(10)

        parse()
        self.assertEqual(config.foo, 1)
        self.assertEqual(config.bar, 10)

    def test_conf_file_w_unknown_ext(self):
        # Conf file with unsupported extension.
        with open(TESTFN, 'w') as f:
            f.write('foo')
        self.addCleanup(unlink, TESTFN)
        with self.assertRaises(ValueError) as cm:
            parse(TESTFN)
        self.assertIn("don't know how to parse", str(cm.exception))
        self.assertIn("extension not supported", str(cm.exception))

    def test_parser_with_no_file(self):
        self.assertRaises(ValueError, parse, file_parser=lambda x: {})

    def test_no_registered_class(self):
        self.assertRaises(Error, parse)

    def test_file_like(self):
        @register()
        class foo:
            foo = 1

        file = io.StringIO()
        with self.assertRaises(Error) as cm:
            parse(file)
        self.assertEqual(
            str(cm.exception),
            "can't determine file format from a file object with no 'name' "
            "attribute")

        file = io.StringIO()
        parse(file, file_parser=lambda x: {})

    def test_parse_called_twice(self):
        @register()
        class config:
            foo = 1
            bar = 2

        parse()
        self.assertRaises(AlreadyParsedError, parse)
        self.assertRaises(AlreadyParsedError, parse_with_envvars)


# ===================================================================
# parse_with_envvar() tests
# ===================================================================


class TestParseWithEnvvars(unittest.TestCase):

    def setUp(self):
        discard()
    tearDown = setUp

    def test_translators_not_callable(self):
        self.assertRaises(TypeError, parse_with_envvars, name_translator=1)
        self.assertRaises(TypeError, parse_with_envvars, value_translator=1)

    def test_envvar_parser_not_callable(self):
        with self.assertRaises(TypeError) as cm:
            parse_with_envvars(envvar_parser=1)
        self.assertIn("not a callable", str(cm.exception))


# ===================================================================
# schema() tests
# ===================================================================


class TestSchema(unittest.TestCase):

    def test_errors(self):
        # no default nor required=True
        self.assertRaisesRegexp(
            ValueError, "specify a default value or set required", schema)
        # not callable validator
        self.assertRaisesRegexp(
            TypeError, "not callable", schema, default=10, validator=1)
        self.assertRaisesRegexp(
            TypeError, "not callable", schema, default=10, validator=['foo'])

# ===================================================================
# exception classes tests
# ===================================================================


class TestExceptions(unittest.TestCase):

    def test_error(self):
        exc = Error('foo')
        self.assertEqual(str(exc), 'foo')
        self.assertEqual(repr(exc), 'foo')

    def test_already_parsed_error(self):
        exc = AlreadyParsedError()
        self.assertIn('already parsed', str(exc))

    def test_already_registered_error(self):
        exc = AlreadyRegisteredError('foo')
        self.assertIn('already registered', str(exc))
        self.assertIn('foo', str(exc))

    def test_not_parsed_error(self):
        exc = NotParsedError()
        self.assertIn('not parsed', str(exc))

    def test_unrecognized_key_error(self):
        exc = UnrecognizedKeyError(key='foo', value='bar')
        self.assertEqual(
            str(exc),
            "config file provides key 'foo' with value 'bar' but key 'foo' "
            "is not defined in the config class")

    def test_required_key_error(self):
        exc = RequiredKeyError(key="foo")
        self.assertEqual(
            str(exc),
            "configuration class requires 'foo' key to be specified via "
            "config file or env var")

    def test_types_mismatch_error(self):
        exc = TypesMismatchError(key="foo", default_value=1, new_value='bar')
        self.assertEqual(
            str(exc),
            "type mismatch for key 'foo' (default_value=1, %s) got "
            "'bar' (%s)" % (type(1), type("")))


# ===================================================================
# get_parsed_conf() tests
# ===================================================================


class TestGetParsedConf(unittest.TestCase):

    def setUp(self):
        discard()
    tearDown = setUp

    def test_root_only(self):
        @register()
        class root_conf:
            root_value = 1

        self.assertRaises(NotParsedError, get_parsed_conf)
        parse()
        self.assertEqual(get_parsed_conf(), {'root_value': 1})

    def test_root_plus_sub(self):
        @register()
        class root_conf:
            root_value = 1

        @register('sub')
        class sub_conf:
            sub_value = 1

        parse()
        self.assertEqual(
            get_parsed_conf(), {'root_value': 1, 'sub': {'sub_value': 1}})

    def test_sub_plus_root(self):
        @register('sub')
        class sub_conf:
            sub_value = 1

        @register()
        class root_conf:
            root_value = 1

        parse()
        self.assertEqual(
            get_parsed_conf(), {'root_value': 1, 'sub': {'sub_value': 1}})

    def test_hidden_key(self):
        @register()
        class config:
            foo = 1
            _hidden = 2

        parse()
        self.assertEqual(
            get_parsed_conf(), {'foo': 1})


# ===================================================================
# @register() tests
# ===================================================================


class TestRegister(unittest.TestCase):

    def setUp(self):
        discard()
    tearDown = setUp

    def test_dictify_and_method(self):
        @register()
        class config:
            foo = 1
            bar = 2
            _hidden = 3

            @classmethod
            def some_method(cls):
                return 1

        self.assertEqual(dict(config), {'foo': 1, 'bar': 2})
        self.assertEqual(config.some_method(), 1)
        parse()
        self.assertEqual(dict(config), {'foo': 1, 'bar': 2})
        self.assertEqual(config.some_method(), 1)

    def test_special_methods(self):
        @register()
        class config:
            """docstring"""
            foo = 1
            bar = 2

            @classmethod
            def some_method(cls):
                return 1

        self.assertEqual(config.__doc__, "docstring")
        self.assertEqual(config.__name__, "config")
        # __len__
        self.assertEqual(len(config), 2)
        # __getitem__
        self.assertEqual(config['foo'], 1)
        # __setitem__
        config['foo'] == 33
        self.assertEqual(config['foo'], 1)
        # __contains__
        assert 'foo' in config
        # should we allow this?
        assert 'some_method' in config
        # __delitem__
        del config['foo']
        assert 'foo' not in config
        self.assertEqual(len(config), 1)
        # __repr__
        repr(config)

    def test_register_twice(self):
        @register()
        class config:
            foo = 1

        with self.assertRaises(AlreadyRegisteredError):
            @register()
            class config_2:
                foo = 1

    def test_decorate_fun(self):
        with self.assertRaises(TypeError) as cm:
            @register()
            def foo():
                pass

        self.assertIn(
            'register decorator is supposed to be used against a class',
            str(cm.exception))


# ===================================================================
# misc tests
# ===================================================================


class TestMisc(unittest.TestCase):

    def test__all__(self):
        dir_confix = dir(confix)
        for name in dir_confix:
            if name in ('configparser', 'logger', 'basestring'):
                continue
            if not name.startswith('_'):
                try:
                    __import__(name)
                except ImportError:
                    if name not in confix.__all__:
                        fun = getattr(confix, name)
                        if fun is None:
                            continue
                        if (fun.__doc__ is not None and
                                'deprecated' not in fun.__doc__.lower()):
                            self.fail('%r not in confix.__all__' % name)

        # Import 'star' will break if __all__ is inconsistent, see:
        # https://github.com/giampaolo/psutil/issues/656
        # Can't do `from confix import *` as it won't work on python 3
        # so we simply iterate over __all__.
        for name in confix.__all__:
            self.assertIn(name, dir_confix)

    def test_version(self):
        self.assertEqual('.'.join([str(x) for x in confix.version_info]),
                         confix.__version__)

    def test_setup_script(self):
        here = os.path.abspath(os.path.dirname(__file__))
        setup_py = os.path.realpath(os.path.join(here, 'setup.py'))
        module = imp.load_source('setup', setup_py)
        self.assertRaises(SystemExit, module.setup)
        self.assertEqual(module.get_version(), confix.__version__)


def main():
    verbosity = 1 if 'TOX' in os.environ else 2
    unittest.main(verbosity=verbosity)


if __name__ == '__main__':
    main()
