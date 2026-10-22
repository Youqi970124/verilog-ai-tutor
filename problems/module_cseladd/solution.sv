module mux2to1(input [15:0] in0, input [15:0] in1, input sel, output [15:0] out);
  assign out = sel ? in1 : in0;
endmodule

module top_module(input [31:0] a, input [31:0] b, output [31:0] sum);
  wire [15:0] low_sum;
  wire low_cout;
  wire [15:0] high_sum0, high_sum1;
  wire high_cout0, high_cout1;
  wire [15:0] high_sum_selected;

  add16 low_adder (.a(a[15:0]), .b(b[15:0]), .cin(1'b0), .sum(low_sum), .cout(low_cout));
  add16 high_adder0 (.a(a[31:16]), .b(b[31:16]), .cin(1'b0), .sum(high_sum0), .cout(high_cout0));
  add16 high_adder1 (.a(a[31:16]), .b(b[31:16]), .cin(1'b1), .sum(high_sum1), .cout(high_cout1));
  mux2to1 high_mux (.in0(high_sum0), .in1(high_sum1), .sel(low_cout), .out(high_sum_selected));

  assign sum = {high_sum_selected, low_sum};
endmodule
